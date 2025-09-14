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
from src.utils.mock_data import generate_mock_rows, generate_curated_duplicates, generate_enhanced_duplicates, generate_anomaly_data
from src.analysis.dedupe import mark_duplicates
from src.analysis.diff import load_with_fingerprint, compute_differences


try:
    st.set_page_config(page_title="Real Estate Explorer", layout="wide")
except Exception:
    # Ignore if Streamlit already initialized page config in this environment
    pass

# Mobile-responsive styling for Streamlit (Cloud + local)
st.markdown(
    """
    <style>
    .block-container {
        max-width: 1600px; 
        padding-left: 1rem; 
        padding-right: 1rem;
    }
    
    /* Mobile responsiveness */
    @media (max-width: 768px) {
        .block-container {
            padding-left: 0.5rem;
            padding-right: 0.5rem;
        }
        
        /* Make sidebar more compact on mobile */
        .css-1d391kg {
            width: 200px !important;
        }
        
        /* Adjust chart sizes for mobile */
        .stPlotlyChart {
            width: 100% !important;
        }
        
        /* Make buttons stack better on mobile */
        .stButton > button {
            width: 100%;
            margin-bottom: 0.5rem;
        }
        
        /* Improve text readability on mobile */
        .stMarkdown {
            font-size: 14px;
        }
        
        /* Make expanders more touch-friendly */
        .streamlit-expanderHeader {
            padding: 0.75rem;
            font-size: 16px;
        }
        
        /* Adjust data table for mobile */
        .stDataFrame {
            font-size: 12px;
        }
        
        /* Make filters more compact */
        .stSelectbox, .stMultiselect, .stSlider {
            margin-bottom: 0.5rem;
        }
    }
    
    /* Tablet responsiveness */
    @media (min-width: 769px) and (max-width: 1024px) {
        .block-container {
            max-width: 1200px;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(show_spinner=False)
def load_data_from_db() -> pd.DataFrame:
    try:
        engine = get_engine()
        with engine.begin() as conn:
            df = pd.read_sql(text("SELECT * FROM listings"), conn)
        
        # Clean the dataframe to prevent React serialization issues
        if not df.empty:
            # Convert object columns to strings and clean problematic values
            for col in df.columns:
                if df[col].dtype == 'object':
                    # Replace None, NaN, and other problematic values
                    df[col] = df[col].fillna('').astype(str)
                    # Remove any remaining problematic characters
                    df[col] = df[col].str.replace('\x00', '', regex=False)  # Remove null bytes
                    df[col] = df[col].str.replace('\r', '', regex=False)    # Remove carriage returns
                    df[col] = df[col].str.replace('\n', ' ', regex=False)   # Replace newlines with spaces
            
            # Ensure numeric columns are properly typed
            numeric_cols = ['price', 'surface', 'rooms']
            for col in numeric_cols:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                    df[col] = df[col].fillna(0)  # Fill NaN with 0 for numeric columns
        
        return df
    except Exception as e:
        st.error(f"Error loading data from database: {str(e)}")
        return pd.DataFrame()


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


# ==================== ANOMALY DETECTION FUNCTIONS ====================

def detect_price_anomalies(df):
    """Detect price anomalies using statistical methods"""
    anomalies = []
    
    if df.empty or 'price' not in df.columns or 'city' not in df.columns:
        return anomalies
    
    # Calculate city-based price statistics
    city_stats = df.groupby('city')['price'].agg(['mean', 'std', 'min', 'max']).reset_index()
    
    for _, row in df.iterrows():
        city = row['city']
        price = row['price']
        
        if pd.isna(city) or pd.isna(price):
            continue
            
        city_data = city_stats[city_stats['city'] == city]
        if not city_data.empty:
            city_mean = city_data['mean'].iloc[0]
            city_std = city_data['std'].iloc[0]
            
            # Z-score calculation (values outside 3 standard deviations)
            if city_std > 0:
                z_score = abs((price - city_mean) / city_std)
                if z_score > 3:
                    anomalies.append({
                        'type': 'price_anomaly',
                        'city': city,
                        'price': price,
                        'expected_range': f"{city_mean-city_std:.0f} - {city_mean+city_std:.0f}",
                        'z_score': round(z_score, 2),
                        'title': row.get('title', 'N/A')
                    })
    
    return anomalies


def check_data_completeness(df):
    """Check data completeness and missing field analysis"""
    completeness_report = {}
    
    if df.empty:
        return completeness_report
    
    # Calculate missing data percentage for each column
    for col in df.columns:
        missing_count = df[col].isnull().sum()
        total_count = len(df)
        missing_percentage = (missing_count / total_count) * 100
        
        completeness_report[col] = {
            'missing_count': int(missing_count),
            'missing_percentage': round(missing_percentage, 2),
            'status': 'CRITICAL' if missing_percentage > 20 else 'WARNING' if missing_percentage > 5 else 'OK'
        }
    
    return completeness_report


def cross_source_validation(df):
    """Compare data between SeLoger and LeBoncoin sources"""
    inconsistencies = []
    
    if df.empty or 'source' not in df.columns or 'city' not in df.columns or 'price' not in df.columns:
        return inconsistencies
    
    # Compare average prices by city between sources
    city_price_comparison = df.groupby(['city', 'source'])['price'].agg(['mean', 'count']).reset_index()
    
    for city in city_price_comparison['city'].unique():
        city_data = city_price_comparison[city_price_comparison['city'] == city]
        
        if len(city_data) == 2:  # Both sources available
            seloger_data = city_data[city_data['source'] == 'seloger']
            leboncoin_data = city_data[city_data['source'] == 'leboncoin']
            
            if not seloger_data.empty and not leboncoin_data.empty:
                seloger_avg = seloger_data['mean'].iloc[0]
                leboncoin_avg = leboncoin_data['mean'].iloc[0]
                seloger_count = seloger_data['count'].iloc[0]
                leboncoin_count = leboncoin_data['count'].iloc[0]
                
                # Check for significant price differences (>30%)
                if seloger_avg > 0 and leboncoin_avg > 0:
                    price_diff_percentage = abs(seloger_avg - leboncoin_avg) / max(seloger_avg, leboncoin_avg) * 100
                    
                    if price_diff_percentage > 30:
                        inconsistencies.append({
                            'type': 'price_inconsistency',
                            'city': city,
                            'seloger_avg': round(seloger_avg, 2),
                            'leboncoin_avg': round(leboncoin_avg, 2),
                            'difference_percentage': round(price_diff_percentage, 2),
                            'seloger_count': int(seloger_count),
                            'leboncoin_count': int(leboncoin_count)
                        })
    
    return inconsistencies


def comprehensive_anomaly_detection(df):
    """Comprehensive anomaly detection system"""
    if df.empty:
        return {
            'report': {'total_issues': 0, 'price_anomalies': 0, 'cross_source_inconsistencies': 0},
            'critical_issues': [],
            'price_anomalies': [],
            'inconsistencies': [],
            'completeness': {}
        }
    
    # Run all anomaly detection checks
    price_anomalies = detect_price_anomalies(df)
    completeness = check_data_completeness(df)
    inconsistencies = cross_source_validation(df)
    
    # Generate report
    report = {
        'price_anomalies': len(price_anomalies),
        'cross_source_inconsistencies': len(inconsistencies),
        'total_issues': len(price_anomalies) + len(inconsistencies)
    }
    
    # Identify critical issues
    critical_issues = []
    
    if report['price_anomalies'] > 0:
        critical_issues.append(f"⚠️ {report['price_anomalies']} price anomalies detected")
    
    if report['cross_source_inconsistencies'] > 0:
        critical_issues.append(f"⚠️ {report['cross_source_inconsistencies']} cross-source inconsistencies detected")
    
    # Check for critical data completeness issues
    for field, stats in completeness.items():
        if stats['status'] == 'CRITICAL':
            critical_issues.append(f"🚨 {field} field has {stats['missing_percentage']:.1f}% missing data")
        elif stats['status'] == 'WARNING':
            critical_issues.append(f"⚠️ {field} field has {stats['missing_percentage']:.1f}% missing data")
    
    return {
        'report': report,
        'critical_issues': critical_issues,
        'price_anomalies': price_anomalies,
        'inconsistencies': inconsistencies,
        'completeness': completeness
    }


def show_anomaly_dashboard(df):
    """Display anomaly detection dashboard in Streamlit"""
    with st.expander("🚨 Anomaly Detection Dashboard", expanded=False):
        # Run anomaly detection
        anomaly_results = comprehensive_anomaly_detection(df)
        
        # Summary metrics
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Price Anomalies", anomaly_results['report']['price_anomalies'])
        with col2:
            st.metric("Source Inconsistencies", anomaly_results['report']['cross_source_inconsistencies'])
        with col3:
            st.metric("Total Issues", anomaly_results['report']['total_issues'])
        with col4:
            # Calculate data quality score
            total_fields = len(anomaly_results['completeness'])
            if total_fields > 0:
                ok_fields = sum(1 for stats in anomaly_results['completeness'].values() if stats['status'] == 'OK')
                quality_score = round((ok_fields / total_fields) * 100, 1)
                st.metric("Data Quality Score", f"{quality_score}%")
            else:
                st.metric("Data Quality Score", "N/A")
        
        # Critical issues alert
        if anomaly_results['critical_issues']:
            st.error("🚨 Critical Issues Detected:")
            for issue in anomaly_results['critical_issues']:
                st.write(f"• {issue}")
        else:
            st.success("✅ No critical issues detected!")
        
        # Detailed reports
        if anomaly_results['price_anomalies']:
            st.subheader("🔍 Price Anomalies Details")
            anomaly_df = pd.DataFrame(anomaly_results['price_anomalies'])
            st.dataframe(anomaly_df[['city', 'price', 'expected_range', 'z_score', 'title']], 
                        use_container_width=True, hide_index=True)
        
        if anomaly_results['inconsistencies']:
            st.subheader("🔄 Cross-Source Inconsistencies")
            inconsistency_df = pd.DataFrame(anomaly_results['inconsistencies'])
            st.dataframe(inconsistency_df[['city', 'seloger_avg', 'leboncoin_avg', 'difference_percentage', 
                                         'seloger_count', 'leboncoin_count']], 
                        use_container_width=True, hide_index=True)
        
        # Data completeness report
        if anomaly_results['completeness']:
            st.subheader("📊 Data Completeness Report")
            completeness_df = pd.DataFrame(anomaly_results['completeness']).T
            completeness_df = completeness_df.sort_values('missing_percentage', ascending=False)
            
            # Color code the status
            def color_status(val):
                if val == 'CRITICAL':
                    return 'background-color: #ffcccc'
                elif val == 'WARNING':
                    return 'background-color: #fff3cd'
                else:
                    return 'background-color: #d4edda'
            
            styled_df = completeness_df.style.applymap(color_status, subset=['status'])
            st.dataframe(styled_df, use_container_width=True)


def main():
    st.title("Real Estate Explorer (SeLoger vs Leboncoin)")
    
    # Code Architecture & Technical Details
    with st.expander("🔧 Code Architecture & Technical Details", expanded=False):
        st.markdown("### **📚 Kullanılan Kütüphaneler ve Teknolojiler**")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("""
            **🐍 Python Kütüphaneleri:**
            - **Pandas**: Veri manipülasyonu ve analizi
            - **SQLAlchemy**: Veritabanı ORM ve bağlantı yönetimi
            - **Matplotlib + Seaborn**: Profesyonel veri görselleştirme
            - **Streamlit**: Web arayüzü ve dashboard oluşturma
            - **Hashlib**: SHA1 fingerprinting için güvenli hash
            - **Pathlib**: Dosya yolu yönetimi
            - **Random**: Mock veri üretimi
            - **NumPy**: Sayısal hesaplamalar
            """)
        
        with col2:
            st.markdown("""
            **🗄️ Veritabanı ve Depolama:**
            - **SQLite**: Hafif, dosya tabanlı veritabanı
            - **Excel Export**: Pandas ile .xlsx dosya oluşturma
            - **CSV Export**: Veri paylaşımı için standart format
            - **JSON**: Yapılandırılmış veri formatı
            - **Git**: Versiyon kontrolü ve işbirliği
            """)
        
        st.markdown("### **⚠️ Dikkat Edilen Kritik Noktalar**")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("""
            **🔒 Veri Güvenliği:**
            - **SQL Injection Koruması**: SQLAlchemy ORM kullanımı
            - **Input Validation**: Kullanıcı girdilerinin doğrulanması
            - **Error Handling**: Kapsamlı hata yakalama ve yönetimi
            - **Data Sanitization**: Veri temizleme ve normalizasyon
            - **Type Safety**: Veri tiplerinin kontrolü
            """)
        
        with col2:
            st.markdown("""
            **⚡ Performans Optimizasyonu:**
            - **Caching**: @st.cache_data ile veri önbellekleme
            - **Lazy Loading**: Veri yükleme optimizasyonu
            - **Memory Management**: Büyük veri setleri için bellek yönetimi
            - **Query Optimization**: Veritabanı sorgu optimizasyonu
            - **Responsive Design**: Mobil uyumlu arayüz
            """)
        
        st.markdown("### **🏗️ Mimari Tasarım Prensipleri**")
        
        st.markdown("""
        **1. Modüler Yapı:**
        - Her modül tek bir sorumluluğa sahip (Single Responsibility)
        - Bağımlılıklar minimize edildi (Dependency Inversion)
        - Kod tekrarı önlendi (DRY Principle)
        - Kolay test edilebilir yapı
        
        **2. Hata Yönetimi:**
        - Try-catch blokları ile güvenli kod
        - Kullanıcı dostu hata mesajları
        - Graceful degradation (kademeli bozulma)
        - Logging ve monitoring
        
        **3. Veri Bütünlüğü:**
        - Duplicate detection algoritmaları
        - Data validation kuralları
        - Cross-source consistency checks
        - Anomaly detection sistemleri
        
        **4. Kullanıcı Deneyimi:**
        - Responsive design (mobil uyumlu)
        - Real-time updates
        - Intuitive interface design
        - Performance optimization
        """)
        
        st.markdown("### **📊 İş Değeri ve Uygulama Alanları**")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("""
            **💼 Joreca Pozisyonu İçin:**
            - **Data Pipeline Management**: End-to-end veri akışı
            - **Quality Control**: Veri kalitesi kontrolü
            - **Anomaly Detection**: Anomali tespiti ve raporlama
            - **Monitoring**: Real-time dashboard ve alerting
            - **Automation**: Otomatik veri işleme
            """)
        
        with col2:
            st.markdown("""
            **🎯 Teknik Yetkinlikler:**
            - **SQL**: Karmaşık sorgular ve veri analizi
            - **Python**: Data science ve automation
            - **Web Scraping**: Veri toplama teknikleri
            - **Visualization**: Business intelligence
            - **Cloud Deployment**: Production ortamı
            """)
        
        st.markdown("### **🚀 Production Ready Özellikler**")
        
        st.markdown("""
        **Cloud Deployment:**
        - **Streamlit Cloud**: Otomatik CI/CD pipeline
        - **Git Integration**: Version control ve collaboration
        - **Environment Variables**: Configuration management
        - **Error Monitoring**: Production error tracking
        
        **Scalability & Maintenance:**
        - **Modular Design**: Kolay genişletilebilir yapı
        - **Database Abstraction**: Farklı veritabanlarına geçiş kolaylığı
        - **API Ready**: REST API entegrasyonu için hazır
        - **Documentation**: Self-documenting code
        - **Testing**: Unit test ve integration test hazır
        """)

    # Controls
    col1, col2 = st.columns(2)
    with col1:
        min_rows = st.number_input("Min rows", min_value=50, max_value=10000, value=200, step=50)
    with col2:
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
                fig_city_dup, ax_city_dup = plt.subplots(figsize=(10, 6))
                
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
                fig_price_dup, ax_price_dup = plt.subplots(figsize=(10, 6))
                
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

    # Anomaly Detection Dashboard
    show_anomaly_dashboard(fdf)

    with st.expander("📋 Dataset", expanded=True):
        if fdf.empty:
            st.warning("No data available to display.")
            return
        
        try:
            # Clean the dataframe for display to avoid React errors
            display_df = fdf.copy()
            
            # Convert problematic columns to strings to avoid React serialization issues
            for col in display_df.columns:
                if display_df[col].dtype == 'object':
                    display_df[col] = display_df[col].astype(str)
            
            # Sort and reset index
            display_df = display_df.sort_values("price", na_position="last").reset_index(drop=True)
            
            # Limit the number of rows displayed to prevent memory issues
            max_rows = 1000
            if len(display_df) > max_rows:
                st.info(f"Showing first {max_rows} rows out of {len(display_df)} total records")
                display_df = display_df.head(max_rows)
            
            st.dataframe(display_df, hide_index=True)
            
            # Show summary stats
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Total Records", len(fdf))
            with col2:
                st.metric("Unique Cities", fdf['city'].nunique() if 'city' in fdf.columns else 0)
            with col3:
                st.metric("Price Range", f"€{fdf['price'].min():,.0f} - €{fdf['price'].max():,.0f}" if 'price' in fdf.columns and not fdf['price'].isna().all() else "N/A")
                
        except Exception as e:
            st.error(f"Error displaying data: {str(e)}")
            st.write("Raw data preview (first 10 rows):")
            try:
                # Try a simpler display method
                for i, row in fdf.head(10).iterrows():
                    st.write(f"Row {i+1}: {dict(row)}")
            except Exception as e2:
                st.write(f"Even simple display failed: {str(e2)}")
                st.write("Data shape:", fdf.shape)
                st.write("Columns:", list(fdf.columns))

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
                fig1, ax1 = plt.subplots(figsize=(9, 6))
                sns.histplot(fdf["price"].dropna(), bins=25, kde=True, color='skyblue', alpha=0.7, ax=ax1)
                ax1.set_title(f"💰 Price Distribution ({len(fdf)} records)", fontsize=14, fontweight='bold', pad=20)
                ax1.set_xlabel("Price (€)", fontsize=12)
                ax1.set_ylabel("Count", fontsize=12)
                ax1.grid(True, alpha=0.3)
                plt.tight_layout()
                st.pyplot(fig1, clear_figure=True)
            with col2:
                fig2, ax2 = plt.subplots(figsize=(9, 6))
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
                    fig3, ax3 = plt.subplots(figsize=(9, 6))
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
                    fig4, ax4 = plt.subplots(figsize=(9, 6))
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
                    fig5, ax5 = plt.subplots(figsize=(9, 6))
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
                    fig6, ax6 = plt.subplots(figsize=(9, 6))
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


