
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import os
import json
from pathlib import Path
import gspread
from google.oauth2.service_account import Credentials

# -------------------------------------------------------------------------
# 1. Google Permissions
# -------------------------------------------------------------------------
SHEET_KEY = "1rgS_NxsZjDkPE07kEpuYxvwktyROXKUfYBk-4t9bkqA"
SHEET_NAME = "participant_data"
CREDENTIALS_PATH = Path("C:/Users/Jack Helmsing/Documents/Helmsing Army Documents/Recruiting/gitignore/atomic-monument-448919-i5-8043c996fb0e.json")

def authorize_gspread():
    """
    Authorize gspread client with loaded credentials.
    """
    try:
        creds = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=[
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ])
        client = gspread.authorize(creds)
        return client
    except Exception as e:
        st.error(f"Error authorizing gspread client: {e}")
        st.stop()

def get_google_sheet(client, sheet_key, worksheet_name="participant_data"):
    """
    Access a specific worksheet in the Google Sheet.
    """
    try:
        sheet = client.open_by_key(sheet_key)
        worksheet = sheet.worksheet(worksheet_name)
        data = worksheet.get_all_records(expected_headers=worksheet.row_values(1))
        return pd.DataFrame(data)
    except gspread.SpreadsheetNotFound:
        st.error("Google Sheet not found. Please check the SHEET_KEY.")
        st.stop()
    except gspread.WorksheetNotFound:
        st.error(f"Worksheet '{worksheet_name}' not found in the Google Sheet.")
        st.stop()
    except Exception as e:
        st.error(f"Error accessing Google Sheet: {e}")
        st.stop()

# -------------------------------------------------------------------------
# 2. File Paths
# -------------------------------------------------------------------------
# Get the current script's directory (app-two/src/)
current_dir = Path(__file__).parent.resolve()

# Define the monorepo root directory (two levels up from app-two/src/)
repo_root = current_dir.parent.parent

# Define paths to App Two's input CSVs
skillset_cost_worksheet_path = repo_root / 'app-one' / 'data' / 'input' / 'Skillset_cost_worksheet_CSV.csv'
# Load GI Bill Reduction data
gi_bill_path = repo_root / 'app-two' / 'data' / 'input' / 'GI_Bill_Application.csv'

try:
    gi_bill_df = pd.read_csv(gi_bill_path)
except FileNotFoundError as e:
    print(f"GI Bill reference sheet not found: {e}")
    exit()
except Exception as e:
    print(f"Error loading GI Bill reference sheet: {e}")
    exit()

# Define Paths to App Two's output CSVs
output_csv_path = current_dir.parent / "data" / "output" / "financial_model_plot.csv"
output_html_path = current_dir.parent / "data" / "output" / "plotly_bar_chart_race.html"

# -------------------------------------------------------------------------
# 3. Load & Merge
# -------------------------------------------------------------------------
# Load data from google sheet
client = authorize_gspread()
participant_df = get_google_sheet(client, SHEET_KEY, SHEET_NAME)

# Check if DataFrame is empty before processing
if participant_df.empty:
    st.warning("🚨 No participant data found! Please have participants fill out their surveys first.")
    st.stop()
    
# Load data from local files
try:
    skill_df = pd.read_csv(skillset_cost_worksheet_path)
except FileNotFoundError as e:
    print(f"File not found: {e}")
    exit()
except Exception as e:
    print(f"Error loading files: {e}")
    exit()

# Remove extra spaces in column names
participant_df.columns = participant_df.columns.str.strip()
skill_df.columns = skill_df.columns.str.strip()

# Merge on 'Career' (participant_df) vs 'Profession' (skill_df)
merged_data = participant_df.merge(skill_df, on="Profession", how="left") \
.merge(gi_bill_df, on="Profession", how="left")

# -------------------------------------------------------------------------
# 4. Calculate Monthly Net Worth
# -------------------------------------------------------------------------
def calculate_monthly_financials(row, skillset_df, gi_bill_df):
    """
    Calculates net worth month-by-month over 25 years (300 months),
    ensuring correct loan reference, savings growth, and GI Bill application.
    """
    total_months = 300  # 25 years * 12 months
    monthly_savings_rate = (1 + 0.05) ** (1/12) - 1  # 5% annual return, compounded monthly

    # Extract key participant details
    yrs_school = int(row.get('Years School', 0) * 12)  # Convert years to months
    first_savings_month = yrs_school + 1  # First month after school ends
    monthly_savings = row.get('Savings', 0.0)  # Monthly savings amount
    is_military = row.get("Who Pays for College", "").strip().lower() == "military"

    # Select the correct student loan dataset based on military status
    loan_source = gi_bill_df if is_military else skillset_df

    # Ensure column names are standardized
    loan_source.columns = loan_source.columns.str.lower().str.strip()

    # Check for correct participant identifier
    participant_col = "name"  # Change if necessary after checking columns
    if participant_col not in loan_source.columns:
        raise KeyError(f"Column '{participant_col}' not found in dataset. Available columns: {loan_source.columns}")

    # Get the initial loan balance
    loan_balance = loan_source.loc[loan_source[participant_col] == row[participant_col], "month 1"].values
    loan_balance = float(loan_balance[0]) if len(loan_balance) > 0 else 0.0
    loan_balance = min(loan_balance, 0)  # Ensure negative balance

    # Initialize savings balance and tracking list
    savings_balance = 0.0
    monthly_records = []

    # Simulate monthly financials over 25 years
    for month in range(1, total_months + 1):
        # Apply savings growth and contributions after school
        if month >= first_savings_month:
            savings_balance *= (1 + monthly_savings_rate)  # Apply interest
            savings_balance += monthly_savings  # Add monthly savings contribution

        # Apply student loan payments for non-military participants (first 15 years)
        if not is_military and month <= 180:
            col_name = f"month {month}"
            loan_payment = loan_source.loc[loan_source[participant_col] == row[participant_col], col_name].values
            loan_payment = float(loan_payment[0]) if len(loan_payment) > 0 else 0.0
            loan_balance += loan_payment  # Loan payments decrease balance

        # Calculate net worth (savings + loan balance)
        net_worth = savings_balance + loan_balance

        # Store results in a structured format
        monthly_records.append({
            "Month": month,
            "Savings Balance": savings_balance,
            "Loan Balance": loan_balance,
            "Net Worth": net_worth
        })

    return monthly_records

# -------------------------------------------------------------------------
# 5. Fill Missing Columns
# -------------------------------------------------------------------------
for col in ['Years in School', 'Savings During School', 'Savings']:
    if col in merged_data.columns:
        merged_data[col] = merged_data[col].fillna(0)

for i in range(1, 181):
    c_name = f"month {i}"
    if c_name in merged_data.columns:
        merged_data[c_name] = merged_data[c_name].fillna(0)

# -------------------------------------------------------------------------
# 6. Add Net Worth Column
# -------------------------------------------------------------------------
all_new_columns = {}
all_new_columns["Net Worth Over Time"] = merged_data.apply(calculate_monthly_financials, axis=1)

new_columns_df = pd.DataFrame(all_new_columns)
merged_data = pd.concat([merged_data, new_columns_df], axis=1).copy()

# -------------------------------------------------------------------------
# 7. Expand to Long Format
# -------------------------------------------------------------------------
expanded_rows = []
for _, row in merged_data.iterrows():
    for (m_val, net_worth) in row['Net Worth Over Time']:
        expanded_rows.append({
            'Name': row['Name'],
            'Profession': row['Profession'],
            'Month': m_val,
            'Net Worth': net_worth
        })

expanded_df = pd.DataFrame(expanded_rows)

# -------------------------------------------------------------------------
# 8. Accounting-Style Label
# -------------------------------------------------------------------------
expanded_df['Net Worth Label'] = expanded_df['Net Worth'].apply(
    lambda x: f"(${abs(x):,.2f})" if x < 0 else f"${x:,.2f}"
)

# -------------------------------------------------------------------------
# 9. Save to CSV
# -------------------------------------------------------------------------
try:
    expanded_df.to_csv(output_csv_path, index=False)
    print(f"Monthly data saved to CSV at: {output_csv_path}")
except Exception as e:
    print("Error saving CSV:", e)

# -------------------------------------------------------------------------
# 10. Create Bar Chart Figure
# -------------------------------------------------------------------------
fig = px.bar(
    expanded_df,
    x="Net Worth",
    y="Name",
    orientation="h",
    color="Profession",  # Color by career/profession
    animation_frame="Month",
    text="Net Worth Label",
    title="Net Worth Over 25 Years - Yearly Slider & Pause Fix",
    labels={
        "Net Worth": "Net Worth ($)",
        "Name": "Participants",
        "Profession": "Career"
    },
    color_discrete_sequence=px.colors.qualitative.Set2  # Optional
)
fig.update_traces(textposition="outside", cliponaxis=False)

# -------------------------------------------------------------------------
# Remove Default Slider & Updatemenus from Plotly Express
# -------------------------------------------------------------------------
fig.layout.sliders = []
fig.layout.updatemenus = []

# -------------------------------------------------------------------------
# 11. Define Slider Steps (Yearly)
# -------------------------------------------------------------------------
slider_steps = []
for year in range(1, 26):  # 1..25 years
    final_month = year * 12
    slider_steps.append(dict(
        method="animate",
        label=f"Year {year}",
        args=[[
            f"{final_month}"],  # Target frame name
            {
                "mode": "immediate",
                "frame": {"duration": 500, "redraw": True},
                "transition": {"duration": 0},
            }
        ],
    ))

custom_slider = dict(
    active=0,
    steps=slider_steps,
    x=0.1,
    y=-0.3,  # Slider is now higher
    len=0.8,
    xanchor="left",
    yanchor="bottom",
    pad={"t": 50, "b": 10},
    currentvalue={"prefix": "Jump to: "}
)

# -------------------------------------------------------------------------
# 12. Define Play/Pause Buttons
# -------------------------------------------------------------------------
play_pause_menu = dict(
    type="buttons",
    direction="left",
    x=0.1,
    y=-0.4,  # Moved up
    buttons=[
        dict(
            label="Play",
            method="animate",
            args=[None, {"frame": {"duration": 300, "redraw": True}, "transition": {"duration": 0}, "fromcurrent": True}],
        ),
        dict(
            label="Pause",
            method="animate",
            args=[[None], {"mode": "immediate", "frame": {"duration": 0, "redraw": False}, "transition": {"duration": 0}}],
        ),
    ]
)

# -------------------------------------------------------------------------
# 13. Update Layout with Custom Slider & Buttons
# -------------------------------------------------------------------------
fig.update_layout(
    title=dict(
        text="Net Worth Over Time",
        x=0.5,  # Center title
        y=0.95,  # Position it slightly higher
        xanchor="center",
        yanchor="top",
        font=dict(size=24, color="black")
    ),    
    font=dict(color='black'),  # Set all text to black
    xaxis=dict(tickfont=dict(color='black')),  # Set x-axis text to black
    yaxis=dict(tickfont=dict(color='black')),  # Set y-axis text to black
    plot_bgcolor='white',  # Set background to white
    paper_bgcolor='white',  # Ensure full figure background is white
    sliders=[custom_slider],
    updatemenus=[play_pause_menu],
    margin=dict(l=50, r=50, t=50, b=200),  # Reduced bottom margin
    height=900,  # 50% more vertical space
    legend=dict(
        title="Career",
        x=1.05,
        y=1,
        bgcolor="Black",
        bordercolor="White",
        borderwidth=1,
    ),
)

# -------------------------------------------------------------------------
# 14. Save & Show
# -------------------------------------------------------------------------
try:
    fig.write_html(output_html_path)
    print(f"Bar chart saved to HTML at: {output_html_path}")
except Exception as e:
    print("Error saving HTML file:", e)

st.plotly_chart(fig) 

print("Script complete.")
