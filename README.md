MoveInSync Play Store Review Analysis

Live Dashboard: https://move-in-sync-play-store-review-anal-one.vercel.app/

Backend Deployment: https://moveinsync-play-store-review-analysis.onrender.com

Source Code: https://github.com/KarwanKamboj/MoveInSync-play-store-review-analysis-assignment

About the Project

This project analyzes reviews of MoveInSync's Employee Transportation App on the Google Play Store.

The main goal is to understand why users give low ratings, identify common problems, and suggest what the company should improve first.

The project includes a dashboard that creates reports based on the selected date range.

Main Features

Review Collection: Collects public app ratings and written reviews from Google Play.

Data Cleaning: Removes duplicate reviews and prepares the data for analysis.

Review Classification: Groups reviews into 10 common problem categories, such as app crashes, cab delays, scheduling problems, and safety concerns.

Date Selection: Analyze reviews from the last 3, 6, or 12 months, or choose a custom date range.

Trend Comparison: Compare recent reviews with reviews from the previous period to identify changes.

Issue Prioritization: Ranks problems based on how often they appear, their seriousness, recent trends, available evidence, and how easy they may be to fix.

Safety Alerts: Keeps serious safety-related complaints separate from normal product issues.

Report Generation: Creates reports that can be viewed in HTML or exported as PDF.

Data Checks: Warns when there are not enough reviews or when older review data may be incomplete.

Tools and Technologies

Python: Main programming language.

Pandas and NumPy: Clean and analyze review data.

Google Play Scraper and urllib: Collect public app information and reviews.

Regular Expressions: Identify common problems in review text.

Matplotlib: Create charts.

HTML, CSS, and JavaScript: Build the dashboard.

Git and GitHub: Manage and store the project code.

Project Structure

moveinsync-ratings-analysis/
├── app.py # Runs the web application
├── index.html # Dashboard interface
├── presentation.html # Presentation page
├── run_pipeline.py # Runs the analysis process
├── requirements.txt # Required Python packages
├── data/ # Collected and processed data
├── reports/ # Generated reports and charts
├── src/ # Data collection and analysis code
└── tests/ # Tests for the analysis system

How to Run the Project

1. Install the required packages

Open a terminal in the project folder and run:

pip install -r requirements.txt

2. Start the application

Run:

python app.py

Open the local address shown by the application in your browser. The default address is:

http://localhost:8000

3. Generate a report

Select a reporting period.

Choose the comparison period.

Select negative reviews or all reviews.

Click Generate Report.

Export the report as HTML or PDF.

How Issues Are Prioritized

The system considers:

How often users report a problem.

How serious the problem is.

Whether the problem is becoming more common.

How reliable the available evidence is.

How practical the solution may be to implement.

Problems with insufficient evidence are not treated as confirmed priorities. Serious safety complaints are handled separately.

Important Limitations

The analysis uses publicly available Google Play data.

The collected written reviews may not include every review on the store.

Written reviews do not represent all users who leave a star rating without writing a review.

One review may describe more than one problem.

Review data can identify possible problems, but internal company data is needed to confirm their root causes.

Expected Outcome

This project helps MoveInSync understand customer complaints, identify important product and service issues, and decide which improvements to investigate first.

The dashboard can be reused to analyze different time periods and generate updated reports as needed.
