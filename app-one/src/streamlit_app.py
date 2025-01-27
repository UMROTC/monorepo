import streamlit as st
import pandas as pd
from pathlib import Path
import os

import gspread
from google.oauth2.service_account import Credentials

# ----------------------------------------------------------------------------
# 1. GOOGLE SHEETS AUTH
# ----------------------------------------------------------------------------
# We'll authenticate using your service account JSON stored in Streamlit Secrets.
# Make sure you have something like:
# [gcp_service_account]
# type = "service_account"
# ...
# in your secrets TOML.

scope = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

creds = Credentials.from_service_account_info(
    st.secrets["gcp_service_account"],  # <-- Use quotes around gcp_service_account
    scopes=scope
)
gspread_client = gspread.authorize(creds)

# Open your Google Sheet by *key*.
# Example sheet URL: 
#   https://docs.google.com/spreadsheets/d/1rgS_NxsZjDkPE07kEpuYxvwktyROXKUfYBk-4t9bkqA/edit
# The key is what's between "/d/" and "/edit": 1rgS_NxsZjDkPE07kEpuYxvwktyROXKUfYBk-4t9bkqA
sheet = gspread_client.open_by_key("1rgS_NxsZjDkPE07kEpuYxvwktyROXKUfYBk-4t9bkqA")
worksheet = sheet.worksheet("Sheet1")  # Change this if your tab name differs

# ----------------------------------------------------------------------------
# 2. SETUP PATHS FOR CSV INPUTS
# ----------------------------------------------------------------------------
current_dir = Path(__file__).parent.resolve()
repo_root = current_dir.parent.parent

tax_worksheet_path = repo_root / "app-one" / "data" / "input" / "2024_Tax_worksheet_CSV.csv"
skillset_cost_path = repo_root / "app-one" / "data" / "input" / "Skillset_cost_worksheet_CSV.csv"
lifestyle_decisions_path = repo_root / "app-one" / "data" / "input" / "Lifestyle_decisions_CSV.csv"

# ----------------------------------------------------------------------------
# 3. LOAD CSV DATA
# ----------------------------------------------------------------------------
try:
    tax_data = pd.read_csv(tax_worksheet_path)
    skillset_data = pd.read_csv(skillset_cost_path)
    lifestyle_data = pd.read_csv(lifestyle_decisions_path)
except FileNotFoundError as e:
    st.error(f"Error loading CSV files: {e}")
    st.stop()

# Convert to numeric where needed
skillset_data["Savings During School"] = pd.to_numeric(
    skillset_data["Savings During School"], errors="coerce"
).fillna(0)
skillset_data["Average Salary"] = pd.to_numeric(
    skillset_data["Average Salary"], errors="coerce"
).fillna(0)

# ----------------------------------------------------------------------------
# 4. TAX FUNCTIONS
# ----------------------------------------------------------------------------
def calculate_tax(income, tax_brackets):
    """Compute progressive tax based on brackets."""
    tax = 0
    for _, row in tax_brackets.iterrows():
        lower = row["Lower Bound"]
        upper = row["Upper Bound"] if not pd.isna(row["Upper Bound"]) else float("inf")
        rate = row["Rate"]
        if income > lower:
            taxable = min(income, upper) - lower
            tax += taxable * rate
        else:
            break
    return tax

def calculate_tax_by_status(income, marital_status, tax_data):
    """Calculate total federal + state tax for a given marital status."""
    tax_brackets = tax_data[
        (tax_data["Status"] == marital_status) & (tax_data["Type"] == "Federal")
    ]
    state_brackets = tax_data[
        (tax_data["Status"] == marital_status) & (tax_data["Type"] == "State")
    ]

    if tax_brackets.empty or state_brackets.empty:
        st.error("Tax data is missing or invalid. Please check your CSV.")
        return 0, 0, 0, 0

    standard_deduction = tax_brackets.iloc[0]["Standard Deduction"]
    taxable_income = max(0, float(income) - float(standard_deduction))

    federal_tax = calculate_tax(taxable_income, tax_brackets)
    state_tax = calculate_tax(taxable_income, state_brackets)
    total_tax = federal_tax + state_tax
    return taxable_income, federal_tax, state_tax, total_tax

# ----------------------------------------------------------------------------
# 5. FUNCTION TO SAVE DATA TO GOOGLE SHEETS
# ----------------------------------------------------------------------------
def save_participant_data(data_frame):
    """
    Appends each row of data_frame to the 'Sheet1' worksheet in your Google Sheet.
    """
    try:
        rows_to_add = data_frame.values.tolist()
        for row in rows_to_add:
            worksheet.append_row(row, value_input_option="RAW")

        st.success("Your budget has been submitted and saved to Google Sheets successfully!")
    except Exception as e:
        st.error(f"Failed to save participant data to Google Sheets: {e}")

# ----------------------------------------------------------------------------
# 6. STREAMLIT APP LOGIC
# ----------------------------------------------------------------------------
st.title("Budget Simulator")

# Step 1: Participant Name
st.header("Step 1: Enter Your Name")
participant_name = st.text_input("Name")

# Step 2: Career Choice
st.header("Step 2: Choose Your Career")
career = st.selectbox("Select a Career", skillset_data["Profession"])
selected_career = skillset_data[skillset_data["Profession"] == career].iloc[0]
if selected_career["Requires School"] == "yes":
    salary = selected_career["Savings During School"]
else:
    salary = selected_career["Average Salary"]

# Step 3: Marital Status
st.header("Step 3: Choose Your Marital Status")
marital_status = st.radio("Marital Status", ["Single", "Married"])

(
    taxable_income,
    federal_tax,
    state_tax,
    total_tax,
) = calculate_tax_by_status(salary, marital_status, tax_data)

standard_deduction = tax_data[tax_data["Status"] == marital_status].iloc[0]["Standard Deduction"]
st.write(f"**Annual Salary:** ${salary:,.2f}")
st.write(f"Standard Deduction: ${standard_deduction:,.2f}")
st.write(f"Taxable Income: ${taxable_income:,.2f}")
st.write(f"Federal Tax: ${federal_tax:,.2f}")
st.write(f"State Tax: ${state_tax:,.2f}")
st.write(f"Total Tax: ${total_tax:,.2f}")

monthly_income_after_tax = (salary - federal_tax - state_tax) / 12
st.write(f"**Monthly Income After Tax:** ${monthly_income_after_tax:,.2f}")

# Sidebar for remaining budget
st.sidebar.header("Remaining Monthly Budget")
remaining_budget_display = st.sidebar.empty()
remaining_budget_message = st.sidebar.empty()

# Initialize variables
remaining_budget = monthly_income_after_tax
expenses = 0
savings = 0
selected_lifestyle_choices = {}

# Step 4: Military Service
st.header("Step 4: Military Service")
military_service_choice = st.selectbox(
    "Choose your military service option", ["No", "Part Time", "Full Time"], key="Military_Service"
)
selected_lifestyle_choices["Military Service"] = {"Choice": military_service_choice, "Cost": 0}

# Define restrictions based on military service
restricted_options = {
    "No": ["Military"],
    "Part Time": ["Military"],
    "Full Time": []
}

# Step 5: Lifestyle Choices (Except Savings)
st.header("Step 5: Make Lifestyle Choices")
lifestyle_categories = list(lifestyle_data["Category"].unique())

for idx, category in enumerate(lifestyle_categories):
    if category == "Savings":
        continue  # We'll handle Savings separately

    st.subheader(category)
    options = lifestyle_data[lifestyle_data["Category"] == category]["Option"].tolist()

    # Restrict "Military" if needed
    if "Military" in options and military_service_choice in restricted_options:
        options = [op for op in options if op not in restricted_options[military_service_choice]]

    choice = st.selectbox(f"Choose your {category.lower()}", options, key=f"{category}_choice_{idx}")

    cost = lifestyle_data[
        (lifestyle_data["Category"] == category) & (lifestyle_data["Option"] == choice)
    ]["Monthly Cost"].values[0]

    if remaining_budget - cost < 0:
        st.error(
            f"Warning: Choosing {choice} for {category} exceeds your budget by "
            f"${abs(remaining_budget - cost):,.2f}!"
        )
        remaining_budget -= cost
    else:
        remaining_budget -= cost

    expenses += cost
    selected_lifestyle_choices[category] = {"Choice": choice, "Cost": cost}

# Step 5b: Savings
st.subheader("Savings")
savings_options = lifestyle_data[lifestyle_data["Category"] == "Savings"]["Option"].tolist()
savings_choice = st.selectbox("Choose your savings option", savings_options, key="Savings_Choice")

if savings_choice.lower() == "whatever is left":
    savings = remaining_budget
    remaining_budget = 0
else:
    savings_percentage = lifestyle_data[
        (lifestyle_data["Category"] == "Savings") & (lifestyle_data["Option"] == savings_choice)
    ]["Percentage"].values[0]

    if pd.notna(savings_percentage) and isinstance(savings_percentage, str) and "%" in savings_percentage:
        savings_percentage = float(savings_percentage.strip("%")) / 100
        savings = savings_percentage * monthly_income_after_tax
    else:
        savings = 0

    if savings > remaining_budget:
        st.error(
            f"Warning: Your savings choice exceeds your budget by "
            f"${abs(remaining_budget - savings):,.2f}!"
        )
        remaining_budget -= savings
    else:
        remaining_budget -= savings

selected_lifestyle_choices["Savings"] = {"Choice": savings_choice, "Cost": savings}

# Update sidebar
remaining_budget_display.markdown(f"### Remaining Monthly Budget: ${remaining_budget:,.2f}")
if remaining_budget > 0:
    remaining_budget_message.success(f"You have ${remaining_budget:,.2f} left.")
elif remaining_budget == 0:
    remaining_budget_message.success("You have balanced your budget!")
else:
    remaining_budget_message.error(f"You have overspent by ${-remaining_budget:,.2f}!")

# Display a summary of all choices
st.subheader("Lifestyle Choices Summary")
for cat, details in selected_lifestyle_choices.items():
    st.write(f"**{cat}:** {details['Choice']} - ${details['Cost']:,.2f}")

# Step 6: Submit
st.header("Step 6: Submit Your Budget")
st.write(f"**Remaining Budget:** ${remaining_budget:,.2f}")

if participant_name and career and remaining_budget == 0:
    submit = st.button("Submit")
    if submit:
        # Build the DataFrame
        data = pd.DataFrame({
            "Name": [participant_name],
            "Profession": [career],
            "Military Service": [selected_lifestyle_choices.get("Military Service", {}).get("Choice", "No")],
            "Savings": [savings],
        })
        save_participant_data(data)
