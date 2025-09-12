import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns


def plot_overview(df: pd.DataFrame, figdir: str) -> None:
    if df.empty:
        return
    sns.set(style="whitegrid")

    # Price distribution
    plt.figure(figsize=(8,4))
    sns.histplot(df["price"].dropna(), bins=30, kde=True)
    plt.title("Price Distribution")
    plt.tight_layout()
    plt.savefig(f"{figdir}/price_distribution.png")
    plt.close()

    # Surface vs Price
    plt.figure(figsize=(6,5))
    sns.scatterplot(data=df, x="surface", y="price", hue="source", alpha=0.6)
    plt.title("Surface vs Price by Source")
    plt.tight_layout()
    plt.savefig(f"{figdir}/surface_vs_price.png")
    plt.close()

    # Agency vs Private counts
    if "agency_or_private" in df.columns:
        plt.figure(figsize=(6,4))
        sns.countplot(data=df, x="agency_or_private", hue="source")
        plt.title("Agency vs Private")
        plt.tight_layout()
        plt.savefig(f"{figdir}/agency_private_counts.png")
        plt.close()
