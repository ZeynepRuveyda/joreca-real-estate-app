# Real Estate Data Analysis App

A comprehensive real estate data analysis application that scrapes, processes, and visualizes property listings from SeLoger and LeBoncoin.

## Features

- **Data Scraping**: Automated scraping from SeLoger and LeBoncoin
- **Duplicate Detection**: Intelligent duplicate identification across platforms
- **Data Analysis**: Comprehensive market trend analysis
- **Interactive Dashboard**: Streamlit-based web interface
- **Visualizations**: Beautiful charts and graphs using Matplotlib and Seaborn
- **Filtering**: Advanced filtering by city, price, agency type, etc.

## Tech Stack

- **Python 3.13**
- **Streamlit** - Web interface
- **Pandas** - Data manipulation
- **Matplotlib & Seaborn** - Visualizations
- **SQLite** - Data storage
- **Selenium** - Web scraping
- **BeautifulSoup** - HTML parsing

## Installation

1. Clone the repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Run the application:
   ```bash
   streamlit run src/app.py
   ```

## Usage

1. **Generate Data**: Click "Generate Enhanced Duplicates" to create sample data
2. **Filter Data**: Use the sidebar filters to narrow down results
3. **Analyze Duplicates**: Explore duplicate analysis in the collapsible section
4. **View Visualizations**: Check out the interactive charts and graphs

## Data Structure

The application processes real estate listings with the following fields:
- Title, City, Price, Surface Area, Rooms
- Source (SeLoger/LeBoncoin)
- Agency/Private classification
- Listing type (Sale/Rental)

## License

MIT License