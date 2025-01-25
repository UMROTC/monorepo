import streamlit as st
import pandas as pd
from pathlib import Path
import os

# Get the current script's directory (app-two/src/)
current_dir = Path(__file__).parent.resolve()

# Define the monorepo root directory (two levels up from app-two/src/)
repo_root = current_dir.parent.parent

# Define paths to App One's input CSVs
tax_worksheet_path = repo_root / 'app-one' / 'data' / 'input' / '2024_Tax_worksheet_CSV.csv'
skillset_cost_path = repo_root / 'app-one' / 'data' / 'input' / 'Skillset_cost_worksheet_CSV.csv'
lifestyle_decisions_path = repo_root / 'app-one' / 'data' / 'input' / 'Lifestyle_decisions_CSV.csv'

# Define path to save output CSV in App One's output directory
output_csv_path = repo_root / 'app-one' / 'data' / 'output' / 'participant_data.csv'

# Load the data from the CSV files
try:
    tax_data = pd.read_csv(tax_worksheet_path)
    skillset_data = pd.read_csv(skillset_cost_path)
    lifestyle_data = pd.read_csv(lifestyle_decisions_path)
except FileNotFoundError as e:
    st.error(f"Error loading CSV files: {e}")
    st.stop()

# Convert numeric columns safely
skillset_data["Savings During School"] = pd.to_numeric(skillset_data["Savings During School"], errors="coerce").fillna(0)
skillset_data["Average Salary"] = pd.to_numeric(skillset_data["Average Salary"], errors="coerce").fillna(0)

# Function to calculate progressive tax
def calculate_tax(income, tax_brackets):
    tax = 0
    for _, row in tax_brackets.iterrows():
        lower = row['Lower Bound']
        upper = row['Upper Bound'] if not pd.isna(row['Upper Bound']) else float('inf')
        rate = row['Rate']
        if income > lower:
            taxable = min(income, upper) - lower
            tax += taxable * rate
        else:
            break
    return tax

def calculate_tax_by_status(income, marital_status, tax_data):
    tax_brackets = tax_data[(tax_data['Status'] == marital_status) & (tax_data['Type'] == 'Federal')]
    state_brackets = tax_data[(tax_data['Status'] == marital_status) & (tax_data['Type'] == 'State')]

    if tax_brackets.empty or state_brackets.empty:
        st.error("Tax data is missing or invalid. Please check your CSV.")
        return 0, 0, 0, 0

    standard_deduction = tax_brackets.iloc[0]['Standard Deduction']
    taxable_income = max(0, float(income) - float(standard_deduction))

    federal_tax = calculate_tax(taxable_income, tax_brackets)
    state_tax = calculate_tax(taxable_income, state_brackets)

    total_tax = federal_tax + state_tax
    return taxable_income, federal_tax, state_tax, total_tax

# Define the function to save participant data
def save_participant_data(data_frame, output_path):
    try:
        # Ensure the output directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Append data to the CSV file
        data_frame.to_csv(output_path, index=False, mode='a', header=not output_path.exists())
        st.success("Your budget has been submitted and saved successfully!")
    except Exception as e:
        st.error(f"Failed to save participant data: {e}")

# Streamlit App
st.title("Budget Simulator")

# Step 1: Participant Name
st.header("Step 1: Enter Your Name")
participant_name = st.text_input("Name")

# Step 2: Career Choice
st.header("Step 2: Choose Your Career")
career = st.selectbox("Select a Career", skillset_data["Profession"])
selected_career = skillset_data[skillset_data["Profession"] == career].iloc[0]

# Step 3: Military Service
st.header("Step 3: Military Service")
military_service_choice = st.selectbox("Choose your military service option", ["No", "Part Time", "Full Time"], key="Military_Service")

# Now determine final salary:
# If the career requires school, but the user is Part Time or Full Time military => 
#   "college is paid for" => use Average Salary instead of Savings During School.
if selected_career["Requires School"] == "yes" and military_service_choice in ["Part Time", "Full Time"]:
    st.write("Because you are serving in the military, your college expenses are covered.")
    salary = selected_career["Average Salary"]
elif selected_career["Requires School"] == "yes":
    # No military => use 'Savings During School'
    salary = selected_career["Savings During School"]
else:
    # Does not require school => use 'Average Salary'
    salary = selected_career["Average Salary"]

# Step 4: Marital Status
st.header("Step 4: Choose Your Marital Status")
marital_status = st.radio("Marital Status", ["Single", "Married"])

# Calculate taxes
taxable_income, federal_tax, state_tax, total_tax = calculate_tax_by_status(salary, marital_status, tax_data)
standard_deduction = tax_data[tax_data['Status'] == marital_status].iloc[0]['Standard Deduction']

st.write(f"**Annual Salary:** ${salary:,.2f}")
st.write(f"Standard Deduction: ${standard_deduction:,.2f}")
st.write(f"Taxable Income: ${taxable_income:,.2f}")
st.write(f"Federal Tax: ${federal_tax:,.2f}")
st.write(f"State Tax: ${state_tax:,.2f}")
st.write(f"Total Tax: ${total_tax:,.2f}")

# Calculate monthly income after tax
monthly_income_after_tax = (salary - federal_tax - state_tax) / 12
st.write(f"**Monthly Income After Tax:** ${monthly_income_after_tax:,.2f}")

# Sidebar for remaining budget
st.sidebar.header("Remaining Monthly Budget")
remaining_budget_display = st.sidebar.empty()
remaining_budget_message = st.sidebar.empty()

# Initialize budget tracking
remaining_budget = monthly_income_after_tax
expenses = 0
savings = 0
selected_lifestyle_choices = {}

# Record military service choice in the summary
selected_lifestyle_choices["Military Service"] = {"Choice": military_service_choice, "Cost": 0}

# Adjust the restricted options so that "Military" is only removed for "No" service:
restricted_options = {
    "No": ["Military"],
    "Part Time": [],   # <--- ALLOW "Military" for part-time
    "Full Time": []
}

# Step 5: Make Lifestyle Choices (except Savings)
st.header("Step 5: Make Lifestyle Choices")
lifestyle_categories = list(lifestyle_data["Category"].unique())

for idx, category in enumerate(lifestyle_categories):
    if category == "Savings":
        continue  # Skip savings for now

    st.subheader(category)
    options = lifestyle_data[lifestyle_data["Category"] == category]["Option"].tolist()

    # Restrict "Military" option if necessary
    if "Military" in options and military_service_choice in restricted_options:
        options = [
            option for option in options 
            if option not in restricted_options[military_service_choice]
        ]

    choice = st.selectbox(
        f"Choose your {category.lower()}",
        options,
        key=f"{category}_choice_{idx}"
    )

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

# Handle "whatever is left" logic
if savings_choice.lower() == "whatever is left":
    savings = remaining_budget
    remaining_budget = 0
else:
    savings_percentage = lifestyle_data[
        (lifestyle_data["Category"] == "Savings") & (lifestyle_data["Option"] == savings_choice)
    ]["Percentage"].values[0]

    if pd.notna(savings_percentage) and isinstance(savings_percentage, str) and "%" in savings_percentage:
        savings_percentage = float(savings_percentage.strip('%')) / 100
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

# Display summary
st.subheader("Lifestyle Choices Summary")
for category, details in selected_lifestyle_choices.items():
    st.write(f"**{category}:** {details['Choice']} - ${details['Cost']:,.2f}")

# Step 6: Submit
st.header("Step 6: Submit Your Budget")
st.write(f"**Remaining Budget:** ${remaining_budget:,.2f}")

if participant_name and career and remaining_budget == 0:
    submit = st.button("Submit")
    if submit:
        data = pd.DataFrame({
            "Name": [participant_name],
            "Profession": [career],
            "Military Service": [selected_lifestyle_choices.get("Military Service", {}).get("Choice", "No")],
            "Savings": [savings],
            # Optionally add more fields: e.g., "Final Remaining Budget", "Monthly Income After Tax", etc.
        })
        save_participant_data(data, output_csv_path)
