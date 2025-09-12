import os
import sys
from pathlib import Path
import pandas as pd
import streamlit as st
from sqlalchemy import text
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np

"""Ensure project root is on sys.path for Streamlit Cloud imports"""
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.db import get_engine, create_tables, upsert_listings
from src.utils.mock_data import generate_mock_rows, generate_curated_duplicates, generate_enhanced_duplicates
from src.analysis.dedupe import mark_duplicates
from src.analysis.diff import load_with_fingerprint, compute_differences


try:
    st.set_page_config(page_title="Real Estate Explorer", layout="wide")
except Exception:
    # Ignore if Streamlit already initialized page config in this environment
    pass

# Widen page container on Streamlit (Cloud + local)
st.markdown(
    """
    <style>
    .block-container {max-width: 1600px; padding-left: 1rem; padding-right: 1rem;}
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(show_spinner=False)
def load_data_from_db() -> pd.DataFrame:
    engine = get_engine()
    with engine.begin() as conn:
        df = pd.read_sql(text("SELECT * FROM listings"), conn)
    return df


def ensure_min_rows(min_rows: int = 200):
    df = load_data_from_db()
    if len(df) >= min_rows:
        return
    # generate mock rows to reach min_rows
    need = max(0, min_rows - len(df))
    rows = generate_mock_rows(total=need, duplicate_ratio=0.3)
    engine = get_engine()
    upsert_listings(engine, rows)
    st.cache_data.clear()


def main():
    st.title("Real Estate Explorer (SeLoger vs Leboncoin)")

    # Controls
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        min_rows = st.number_input("Min rows", min_value=50, max_value=10000, value=200, step=50)
    with col2:
        if st.button("Populate to min rows (Mock)"):
            ensure_min_rows(min_rows)
            st.success("Dataset populated with mock data.")
        st.caption("Generate sample data to reach minimum rows")
    with col3:
        if st.button("Generate Enhanced Duplicates"):
            rows = generate_enhanced_duplicates(total=400, duplicate_ratio=0.5)
            upsert_listings(get_engine(), rows)
            st.cache_data.clear()
            st.success(f"Generated {len(rows)} records with 50% duplicates.")
        st.caption("Generate realistic data with many duplicates")
    with col4:
        if st.button("Reload data"):
            st.cache_data.clear()
        st.caption("Refresh data from database")
    with col5:
        export_requested = st.button("Export diffs (Excel+CSV)")
        st.caption("Export differences between sources")

    # Load
    engine = get_engine()
    create_tables(engine)
    try:
        df = load_with_fingerprint() if not st.session_state.get("raw_df") else st.session_state["raw_df"]
    except Exception as e:
        st.error(f"Error loading data: {e}")
        st.info("Click 'Populate to min rows (Mock)' to generate sample records.")
        return
    
    if df.empty:
        st.info("No data yet. Click 'Populate to min rows (Mock)' to generate sample records.")
        return

    # Sidebar Filters
    with st.sidebar:
        st.header("🔍 Filters")
        q = st.text_input("Search in title/description", value="", placeholder="Type to search...")
        
        st.subheader("Source")
        sources = st.multiselect("Select sources", options=sorted(df["source"].dropna().unique()), default=list(sorted(df["source"].dropna().unique())))
        
        st.subheader("Location")
        cities = st.multiselect("Select cities", options=sorted(df["city"].dropna().unique()), default=[])
        
        st.subheader("Property")
        listing_types = st.multiselect("Listing type", options=sorted(df["listing_type"].dropna().unique()), default=[])
        agency_private = st.multiselect("Agency/Private", options=sorted(df["agency_or_private"].dropna().unique()), default=[])
        
        st.subheader("Price")
        price_min, price_max = st.slider("Price range", min_value=int(df["price"].min() or 0), max_value=int(df["price"].max() or 1000000), value=(int(df["price"].min() or 0), int(df["price"].max() or 1000000)))

    fdf = df.copy()
    if sources:
        fdf = fdf[fdf["source"].isin(sources)]
    if cities:
        fdf = fdf[fdf["city"].isin(cities)]
    if listing_types:
        fdf = fdf[fdf["listing_type"].isin(listing_types)]
    if agency_private:
        fdf = fdf[fdf["agency_or_private"].isin(agency_private)]
    fdf = fdf[(fdf["price"].fillna(0) >= price_min) & (fdf["price"].fillna(0) <= price_max)]
    if q:
        ql = q.lower()
        fdf = fdf[(fdf["title"].fillna("").str.lower().str.contains(ql)) | (fdf["description"].fillna("").str.lower().str.contains(ql))]

    # Show current filter summary
    with st.expander("📊 Current Filter Summary", expanded=True):
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Records", len(df))
            st.metric("Filtered Records", len(fdf))
        with col2:
            st.write("**Sources:**")
            st.write(", ".join(sources) if sources else "All")
            st.write("**Cities:**")
            st.write(", ".join(cities) if cities else "All")
        with col3:
            st.write("**Listing Types:**")
            st.write(", ".join(listing_types) if listing_types else "All")
            st.write("**Agency/Private:**")
            st.write(", ".join(agency_private) if agency_private else "All")
        with col4:
            st.write("**Price Range:**")
            st.write(f"€{price_min:,} - €{price_max:,}")
            st.write("**Search:**")
            st.write(f'"{q}"' if q else "None")

    # Duplicate Analysis Section (Collapsible)
    with st.expander("🔍 Duplicate Analysis", expanded=False):
        # Duplicate detection (same home) by fingerprint
        dup_df = mark_duplicates(fdf)
        same_home_groups = dup_df[dup_df["_fingerprint"].duplicated(keep=False)].sort_values("_fingerprint")
        
        if not same_home_groups.empty:
            st.write(f"**Found {same_home_groups['_fingerprint'].nunique()} duplicate groups**")
            
            # Show duplicate groups
            for fingerprint, group in same_home_groups.groupby("_fingerprint"):
                st.write(f"**Group {fingerprint[:8]}...** ({len(group)} listings)")
                st.dataframe(group[["source", "title", "city", "price", "surface", "rooms"]], use_container_width=True)
            
            # Create deduplicated dataset for analysis
            deduplicated_df = dup_df.drop_duplicates(subset=["_fingerprint"], keep="first")
            st.write(f"**Deduplicated dataset:** {len(deduplicated_df)} unique properties (removed {len(fdf) - len(deduplicated_df)} duplicates)")
            
            # Duplicate analysis visualizations - Only City and Price Range
            col1, col2 = st.columns(2)
            
            with col1:
                # Duplicates by City - Count unique duplicate groups per city
                fig_city_dup, ax_city_dup = plt.subplots(figsize=(8, 6))
                
                # Group by fingerprint and get unique cities for each duplicate group
                city_dup_counts = same_home_groups.groupby('_fingerprint')['city'].first().value_counts().head(10)
                
                if not city_dup_counts.empty:
                    colors = plt.cm.Set3(np.linspace(0, 1, len(city_dup_counts)))
                    bars = ax_city_dup.barh(city_dup_counts.index, city_dup_counts.values, 
                                          color=colors, alpha=0.8, edgecolor='black', linewidth=1.5)
                    
                    ax_city_dup.set_title("🏙️ Duplicate Properties by City (Top 10)", fontsize=16, fontweight='bold', pad=25)
                    ax_city_dup.set_xlabel("Number of Unique Duplicate Properties", fontsize=14, fontweight='bold')
                    ax_city_dup.set_ylabel("City", fontsize=14, fontweight='bold')
                    ax_city_dup.grid(True, alpha=0.3, linestyle='--', axis='x')
                    
                    # Add value labels
                    for i, bar in enumerate(bars):
                        width = bar.get_width()
                        ax_city_dup.text(width + 0.1, bar.get_y() + bar.get_height()/2, 
                                       f'{int(width)}', ha='left', va='center', 
                                       fontweight='bold', fontsize=11)
                    
                    # Add statistics
                    total_unique_duplicates = city_dup_counts.sum()
                    top_city = city_dup_counts.index[0]
                    top_count = city_dup_counts.iloc[0]
                    stats_text = f'Total: {total_unique_duplicates} unique duplicates\nTop: {top_city} ({top_count})'
                    ax_city_dup.text(0.02, 0.98, stats_text, transform=ax_city_dup.transAxes, 
                                   fontsize=11, verticalalignment='top', 
                                   bbox=dict(boxstyle='round', facecolor='lightblue', alpha=0.8))
                else:
                    ax_city_dup.text(0.5, 0.5, 'No city data available', 
                                   ha='center', va='center', transform=ax_city_dup.transAxes, 
                                   fontsize=14, fontweight='bold')
                    ax_city_dup.set_title("🏙️ Duplicate Properties by City", fontsize=16, fontweight='bold', pad=25)
                
                plt.tight_layout()
                st.pyplot(fig_city_dup, clear_figure=True)
            
            with col2:
                # Duplicates by Price Range - Count unique duplicate groups per price range
                fig_price_dup, ax_price_dup = plt.subplots(figsize=(8, 6))
                
                # Get unique price data for each duplicate group (take first price from each group)
                unique_price_data = []
                for fingerprint, group in same_home_groups.groupby("_fingerprint"):
                    first_row = group.iloc[0]  # Take first row from each duplicate group
                    if pd.notna(first_row['price']):
                        unique_price_data.append(first_row['price'])
                
                if unique_price_data:
                    # Create price ranges
                    price_ranges = ['0-100k', '100k-200k', '200k-300k', '300k-500k', '500k-750k', '750k+']
                    price_bins = [0, 100000, 200000, 300000, 500000, 750000, float('inf')]
                    
                    price_series = pd.Series(unique_price_data)
                    price_counts = pd.cut(price_series, bins=price_bins, labels=price_ranges, right=False).value_counts().sort_index()
                    
                    colors = plt.cm.viridis(np.linspace(0, 1, len(price_counts)))
                    bars = ax_price_dup.bar(price_counts.index, price_counts.values, 
                                          color=colors, alpha=0.8, edgecolor='black', linewidth=1.5)
                    
                    ax_price_dup.set_title("💰 Duplicate Properties by Price Range", fontsize=16, fontweight='bold', pad=25)
                    ax_price_dup.set_xlabel("Price Range (€)", fontsize=14, fontweight='bold')
                    ax_price_dup.set_ylabel("Number of Unique Duplicate Properties", fontsize=14, fontweight='bold')
                    ax_price_dup.grid(True, alpha=0.3, linestyle='--')
                    ax_price_dup.tick_params(axis='x', rotation=45)
                    
                    # Add value labels
                    for bar in bars:
                        height = bar.get_height()
                        ax_price_dup.text(bar.get_x() + bar.get_width()/2., height + 0.05,
                                        f'{int(height)}', ha='center', va='bottom', 
                                        fontweight='bold', fontsize=11)
                    
                    # Add statistics
                    avg_price = np.mean(unique_price_data)
                    median_price = np.median(unique_price_data)
                    stats_text = f'Avg: €{avg_price:,.0f}\nMedian: €{median_price:,.0f}\nTotal: {len(unique_price_data)}'
                    ax_price_dup.text(0.02, 0.98, stats_text, transform=ax_price_dup.transAxes, 
                                    fontsize=11, verticalalignment='top', 
                                    bbox=dict(boxstyle='round', facecolor='gold', alpha=0.8))
                else:
                    ax_price_dup.text(0.5, 0.5, 'No price data available', 
                                    ha='center', va='center', transform=ax_price_dup.transAxes, 
                                    fontsize=14, fontweight='bold')
                    ax_price_dup.set_title("💰 Duplicate Properties by Price Range", fontsize=16, fontweight='bold', pad=25)
                
                plt.tight_layout()
                st.pyplot(fig_price_dup, clear_figure=True)
            
            # Update the main dataframe to use deduplicated data for analysis
            fdf = deduplicated_df
            
        else:
            st.info("No duplicates found in the dataset.")

    with st.expander("📋 Dataset", expanded=True):
        st.dataframe(fdf.sort_values("price", na_position="last").reset_index(drop=True), use_container_width=True, hide_index=True)

    # Differences between sources
    with st.expander("Differences between sources", expanded=False):
        only_se, only_lb, mismatches = compute_differences(fdf)
        c1, c2 = st.columns(2)
        with c1:
            st.metric("Only SeLoger", len(only_se))
            st.dataframe(only_se[["title", "city", "price", "surface", "rooms", "url"]], use_container_width=True, hide_index=True)
        with c2:
            st.metric("Only Leboncoin", len(only_lb))
            st.dataframe(only_lb[["title", "city", "price", "surface", "rooms", "url"]], use_container_width=True, hide_index=True)

    # Visualizations (auto-updating with current selection)
    # Set beautiful style
    plt.style.use('default')
    sns.set_palette("husl")
    sns.set_style("whitegrid", {'grid.alpha': 0.3})

    # Create filter title
    filter_parts = []
    if sources and len(sources) < len(df["source"].unique()):
        filter_parts.append(f"Sources: {', '.join(sources)}")
    if cities:
        filter_parts.append(f"Cities: {', '.join(cities)}")
    if listing_types:
        filter_parts.append(f"Types: {', '.join(listing_types)}")
    if agency_private:
        filter_parts.append(f"Agency/Private: {', '.join(agency_private)}")
    if q:
        filter_parts.append(f'Search: "{q}"')

    filter_title = f"📊 Visualizations - {len(fdf)} records"
    if filter_parts:
        filter_title += f" | {' | '.join(filter_parts)}"

    with st.expander(filter_title, expanded=True):
        if not fdf.empty:
            # Row 1: Price and Surface analysis
            col1, col2 = st.columns(2)
            with col1:
                fig1, ax1 = plt.subplots(figsize=(7, 5))
                sns.histplot(fdf["price"].dropna(), bins=25, kde=True, color='skyblue', alpha=0.7, ax=ax1)
                ax1.set_title(f"💰 Price Distribution ({len(fdf)} records)", fontsize=14, fontweight='bold', pad=20)
                ax1.set_xlabel("Price (€)", fontsize=12)
                ax1.set_ylabel("Count", fontsize=12)
                ax1.grid(True, alpha=0.3)
                plt.tight_layout()
                st.pyplot(fig1, clear_figure=True)
            with col2:
                fig2, ax2 = plt.subplots(figsize=(7, 5))
                sns.scatterplot(data=fdf, x="surface", y="price", hue="source", alpha=0.8, s=60, ax=ax2)
                ax2.set_title(f"🏠 Surface vs Price by Source ({len(fdf)} records)", fontsize=14, fontweight='bold', pad=20)
                ax2.set_xlabel("Surface (m²)", fontsize=12)
                ax2.set_ylabel("Price (€)", fontsize=12)
                ax2.grid(True, alpha=0.3)
                ax2.legend(title="Source", bbox_to_anchor=(1.05, 1), loc='upper left')
                plt.tight_layout()
                st.pyplot(fig2, clear_figure=True)
            
            # Row 2: City and Type analysis
            col3, col4 = st.columns(2)
            with col3:
                if len(fdf["city"].unique()) > 1:
                    fig3, ax3 = plt.subplots(figsize=(7, 5))
                    city_counts = fdf["city"].value_counts()
                    colors = sns.color_palette("Set3", len(city_counts))
                    bars = ax3.bar(city_counts.index, city_counts.values, color=colors, alpha=0.8)
                    ax3.set_title(f"🏙️ Cities Distribution ({len(fdf)} records)", fontsize=14, fontweight='bold', pad=20)
                    ax3.set_xlabel("City", fontsize=12)
                    ax3.set_ylabel("Count", fontsize=12)
                    ax3.tick_params(axis='x', rotation=45)
                    ax3.grid(True, alpha=0.3)
                    # Add value labels on bars
                    for bar in bars:
                        height = bar.get_height()
                        ax3.text(bar.get_x() + bar.get_width()/2., height + 0.1,
                                f'{int(height)}', ha='center', va='bottom', fontweight='bold')
                    plt.tight_layout()
                    st.pyplot(fig3, clear_figure=True)
                else:
                    st.info(f"🏙️ Single city: {fdf['city'].iloc[0] if not fdf.empty else 'N/A'}")
            with col4:
                if "agency_or_private" in fdf.columns and not fdf["agency_or_private"].isna().all():
                    fig4, ax4 = plt.subplots(figsize=(7, 5))
                    sns.countplot(data=fdf, x="agency_or_private", hue="source", ax=ax4, palette="Set2")
                    ax4.set_title(f"🏢 Agency vs Private ({len(fdf)} records)", fontsize=14, fontweight='bold', pad=20)
                    ax4.set_xlabel("Type", fontsize=12)
                    ax4.set_ylabel("Count", fontsize=12)
                    ax4.grid(True, alpha=0.3)
                    ax4.legend(title="Source", bbox_to_anchor=(1.05, 1), loc='upper left')
                    plt.tight_layout()
                    st.pyplot(fig4, clear_figure=True)
                else:
                    st.info("🏢 No agency/private data available")
            
            # Row 3: Rooms and Listing Type analysis
            col5, col6 = st.columns(2)
            with col5:
                if "rooms" in fdf.columns and not fdf["rooms"].isna().all():
                    fig5, ax5 = plt.subplots(figsize=(7, 5))
                    # Convert rooms to integers and filter out invalid values
                    rooms_data = fdf["rooms"].dropna()
                    rooms_data = rooms_data[rooms_data >= 1]  # Only positive room counts
                    rooms_data = rooms_data.astype(int)  # Convert to integers
                    
                    if not rooms_data.empty:
                        # Use countplot for discrete values instead of histplot
                        sns.countplot(data=rooms_data.to_frame('rooms'), x='rooms', color='lightcoral', alpha=0.7, ax=ax5)
                        ax5.set_title(f"🚪 Rooms Distribution ({len(rooms_data)} records)", fontsize=14, fontweight='bold', pad=20)
                        ax5.set_xlabel("Number of Rooms", fontsize=12)
                        ax5.set_ylabel("Count", fontsize=12)
                        ax5.grid(True, alpha=0.3)
                        
                        # Add value labels on bars
                        for bar in ax5.patches:
                            height = bar.get_height()
                            ax5.text(bar.get_x() + bar.get_width()/2., height + 0.05,
                                    f'{int(height)}', ha='center', va='bottom', fontweight='bold')
                        
                        plt.tight_layout()
                        st.pyplot(fig5, clear_figure=True)
                    else:
                        st.info("🚪 No valid rooms data available")
                else:
                    st.info("🚪 No rooms data available")
            with col6:
                if "listing_type" in fdf.columns and not fdf["listing_type"].isna().all():
                    fig6, ax6 = plt.subplots(figsize=(7, 5))
                    sns.countplot(data=fdf, x="listing_type", hue="source", ax=ax6, palette="viridis")
                    ax6.set_title(f"🏷️ Rent vs Sale ({len(fdf)} records)", fontsize=14, fontweight='bold', pad=20)
                    ax6.set_xlabel("Listing Type", fontsize=12)
                    ax6.set_ylabel("Count", fontsize=12)
                    ax6.grid(True, alpha=0.3)
                    ax6.legend(title="Source", bbox_to_anchor=(1.05, 1), loc='upper left')
                    plt.tight_layout()
                    st.pyplot(fig6, clear_figure=True)
                else:
                    st.info("🏷️ No listing type data available")
        else:
            st.warning("⚠️ No data matches your current filters. Try adjusting your selection.")

    # Export
    if export_requested:
        from src.analysis.diff import export_differences
        # Use relative paths suitable for Streamlit Cloud
        base_dir = os.path.join(os.getcwd(), "data")
        os.makedirs(base_dir, exist_ok=True)
        xlsx_path = os.path.join(base_dir, "source_differences.xlsx")
        csv_dir = base_dir
        export_differences(xlsx_path, csv_dir)
        st.success(f"Exported differences to {xlsx_path} and CSVs in {csv_dir}")


if __name__ == "__main__":
    main()


