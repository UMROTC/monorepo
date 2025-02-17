
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

# Merge on 'Career' (participant_df) vs 'profession' (skill_df)
merged_data = participant_df.merge(skill_df, on="profession", how="left") \
.merge(gi_bill_df, on="profession", how="left")

print("Merged columns:", merged_data.columns.tolist())

# -- Single debug loop to detect any missing profession row --
for i, row in merged_data.iterrows():
    ms = str(row.get("Military Service", "")).lower().strip()
    if ms == "no":
        loan_source = skill_df
    else:
        loan_source = gi_bill_df

    prof = str(row.get("profession", "")).lower().strip()

    matching = loan_source.loc[
        loan_source["profession"].str.lower().str.strip() == prof
    ]
    if matching.empty:
        print(f"[DEBUG] Row={i}, Name='{row.get('Name')}', profession='{row.get('profession')}'"
              f" => NOT FOUND in {'skill_df' if ms=='no' else 'gi_bill_df'}")

# If the debug prints show any missing profession, fix them in your CSVs or participant data
# so that 'skill_df' or 'gi_bill_df' has the same exact 'profession'.


# -------------------------------------------------------------------------
# 4. Calculate Monthly Net Worth
# -------------------------------------------------------------------------
def calculate_monthly_financials(row, skill_df, gi_bill_df):
    total_months = 300
    monthly_rate = (1 + 0.05) ** (1/12) - 1  # ~0.00407 for 5% APR

    # 1) Pull participant's data
    months_school = int(row.get("Months School", 0))
    monthly_in_school_savings = float(row.get("Monthly Savings in School", 0.0))
    monthly_post_school_savings = float(row.get("Monthly Savings", 0.0))

    # 2) Decide which loan data to use
    military_status = str(row.get("Military Service", "")).lower()
    if military_status == "no":
        loan_source = skill_df
    else:
        loan_source = gi_bill_df
    subset = loan_source.loc[loan_source["profession"] == profession]
    if subset.empty:
    # 3a) Identify correct row for the participant's profession
    # Handle the missing profession appropriately.
    # For instance, log a warning and return an empty list or default values.
        print(f"[DEBUG] Profession '{profession}' not found in the selected loan source.")
        return []  # or some default financials
    loan_row = subset.iloc[0]

    # 3b) Identify correct row for the participant's profession
    profession = str(row.get("profession", "")).lower().strip()
    loan_source.columns = loan_source.columns.str.lower().str.strip()
    loan_row = loan_source.loc[loan_source["profession"] == profession].iloc[0]

    # 4) Extract monthly loan values
    loan_values = loan_row[[f"month {i}" for i in range(1, total_months + 1)]].astype(float).values

    # 5) Accumulate savings each month
    accrued_savings = []
    for m in range(1, total_months + 1):
        if m == 1:
            # First month
            if months_school >= 1:  
                # If he's in school for at least 1 month
                current_savings = monthly_in_school_savings
            else:
                # Not in school from month 1 => post-school
                current_savings = monthly_post_school_savings
        else:
            # For subsequent months, look at the previous month's savings
            prev_savings = accrued_savings[-1]
            if m <= months_school:
                # Still in school => no compounding, just add the in-school rate
                current_savings = prev_savings + monthly_in_school_savings
            elif m == (months_school + 1):
                # The first month after school => start compounding + monthly_post_school_savings
                current_savings = prev_savings * (1 + monthly_rate) + monthly_post_school_savings
            else:
                # Fully out of school => compounding + monthly_post_school_savings
                current_savings = prev_savings * (1 + monthly_rate) + monthly_post_school_savings

        accrued_savings.append(current_savings)

    # 6) Net Worth = Accrued Savings + Loan Value
    monthly_financials = []
    for m in range(1, total_months + 1):
        idx = m - 1
        net_worth = accrued_savings[idx] + loan_values[idx]
        monthly_financials.append({
            "Month": m,
            "Accrued Savings": accrued_savings[idx],
            "Loan Value": loan_values[idx],
            "Net Worth": net_worth
        })

    return monthly_financials

# -- Only now call .apply(...) once we fix or confirm no missing rows --
merged_data["Net Worth Over Time"] = merged_data.apply(
    lambda row: calculate_monthly_financials(row, skill_df, gi_bill_df),
    axis=1
)
# -------------------------------------------------------------------------
# 5. Fill Missing Columns
# -------------------------------------------------------------------------
for col in ['Months School', 'Monthly Savings in School', 'Monthly Savings']:
    if col in merged_data.columns:
        merged_data[col] = merged_data[col].fillna(0)

for i in range(1, 301):
    c_name = f"month {i}"
    if c_name in merged_data.columns:
        merged_data[c_name] = merged_data[c_name].fillna(0)

print("Merged columns:", merged_data.columns.tolist())


# -------------------------------------------------------------------------
# 7. Expand to Long Format
# -------------------------------------------------------------------------
expanded_rows = []
for _, row in merged_data.iterrows():  # Iterate over merged_data, not row directly
    for record in row["Net Worth Over Time"]:
        expanded_rows.append({
            "Name": row["Name"],
            "profession": row["profession"],
            "Month": record["Month"],
            "Savings Balance": record["Accrued Savings"],
            "Loan Balance": record["Loan Value"],
            "Net Worth": record["Net Worth"]
        })

# Convert list of dictionaries into a DataFrame
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
    color="profession",  # Color by career/profession
    animation_frame="Month",
    text="Net Worth Label",
    title="Net Worth Over 25 Years - Yearly Slider & Pause Fix",
    labels={
        "Net Worth": "Net Worth ($)",
        "Name": "Participants",
        "profession": "Career"
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
