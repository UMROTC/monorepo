"""
Monthly Bar Chart Race for Net Worth
- Slider increments for yearly frames (1..25 years).
- Play/Pause functionality (Pause truly halts the animation).
- Cleaned up layout calls to avoid duplication.
- Slider and play/pause buttons at the bottom of the page.
"""

import pandas as pd
import numpy as np
import plotly.express as px
import os
from pathlib import Path

# -------------------------------------------------------------------------
# 1. File Paths
# -------------------------------------------------------------------------

# Get the current script's directory (app-two/src/)
current_dir = Path(__file__).parent.resolve()

# Define the monorepo root directory (two levels up from app-two/src/)
repo_root = current_dir.parent.parent

# Define paths to App One's input CSVs
participant_data_path = repo_root / 'app-one' / 'data' / 'input' / 'participant_data.csv'
skillset_cost_worksheet_path = repo_root / 'app-one' / 'data' / 'input' / 'Skillset_cost_worksheet_CSV.csv'

# Define Paths to App Two's output CSVs
output_csv_path = current_dir.parent / "data" / "output" / "financial_model_plot.csv"
output_html_path = current_dir.parent / "data" / "output" / "plotly_bar_chart_race.html"

# -------------------------------------------------------------------------
# 2. Load & Merge
# -------------------------------------------------------------------------
# Load data from local files
try:
    participant_df = pd.read_csv(participant_data_path)
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
merged_data = participant_df.merge(
    skill_df,
    left_on='Career',
    right_on='Profession',
    how='left'
)

# -------------------------------------------------------------------------
# 3. Calculate Monthly Net Worth
# -------------------------------------------------------------------------
def calculate_monthly_financials(row):
    """
    Calculate net worth month-by-month over 25 years = 300 months,
    with 5% annual savings growth and up to 180 monthly loan columns.
    """
    total_months = 25 * 12  # 300
    annual_savings_rate = 0.05
    monthly_savings_rate = (1 + annual_savings_rate)**(1/12) - 1

    # Convert years in school -> months
    yrs_school = row.get('Years in School', 0.0)
    months_in_school = int(yrs_school * 12)

    # Savings contributions
    savings_during_school = row.get('Savings During School', 0.0)
    savings_after_school = row.get('Savings', 0.0)

    savings_balance = 0.0
    monthly_records = []

    for m in range(1, total_months + 1):
        # 1) Grow existing savings
        savings_balance *= (1 + monthly_savings_rate)

        # 2) Add monthly deposit
        if m <= months_in_school:
            savings_balance += savings_during_school
        else:
            savings_balance += savings_after_school

        # 3) Loan balance
        if m <= 180:
            col_name = f"month {m}"
            loan_val = row.get(col_name, 0.0)
            if pd.isna(loan_val):
                loan_val = 0.0
        else:
            loan_val = 0.0

        net_worth = savings_balance + loan_val
        monthly_records.append((m, net_worth))

    return monthly_records

# -------------------------------------------------------------------------
# 4. Fill Missing Columns
# -------------------------------------------------------------------------
for col in ['Years in School', 'Savings During School', 'Savings']:
    if col in merged_data.columns:
        merged_data[col] = merged_data[col].fillna(0)

for i in range(1, 181):
    c_name = f"month {i}"
    if c_name in merged_data.columns:
        merged_data[c_name] = merged_data[c_name].fillna(0)

# -------------------------------------------------------------------------
# 5. Add Net Worth Column
# -------------------------------------------------------------------------
all_new_columns = {}
all_new_columns["Net Worth Over Time"] = merged_data.apply(calculate_monthly_financials, axis=1)

new_columns_df = pd.DataFrame(all_new_columns)
merged_data = pd.concat([merged_data, new_columns_df], axis=1).copy()

# -------------------------------------------------------------------------
# 6. Expand to Long Format
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
# 7. Accounting-Style Label
# -------------------------------------------------------------------------
expanded_df['Net Worth Label'] = expanded_df['Net Worth'].apply(
    lambda x: f"(${abs(x):,.2f})" if x < 0 else f"${x:,.2f}"
)

# -------------------------------------------------------------------------
# 8. Save to CSV
# -------------------------------------------------------------------------
try:
    expanded_df.to_csv(output_csv_path, index=False)
    print(f"Monthly data saved to CSV at: {output_csv_path}")
except Exception as e:
    print("Error saving CSV:", e)

# -------------------------------------------------------------------------
# 9. Create Bar Chart Figure
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
# 10. Define Slider Steps (Yearly)
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
# 11. Define Play/Pause Buttons
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
# 12. Update Layout with Custom Slider & Buttons
# -------------------------------------------------------------------------
fig.update_layout(
    sliders=[custom_slider],
    updatemenus=[play_pause_menu],
    margin=dict(l=50, r=50, t=50, b=200),  # Reduced bottom margin
    height=900,  # 50% more vertical space
    legend=dict(
        title="Career",
        x=1.05,
        y=1,
        bgcolor="rgba(255, 255, 255, 0.8)",
        bordercolor="Black",
        borderwidth=1,
    ),
)

# -------------------------------------------------------------------------
# 13. Save & Show
# -------------------------------------------------------------------------
try:
    fig.write_html(output_html_path)
    print(f"Bar chart saved to HTML at: {output_html_path}")
except Exception as e:
    print("Error saving HTML file:", e)

fig.show()

print("Script complete.")
