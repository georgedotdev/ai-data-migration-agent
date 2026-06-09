import pandas as pd
from profiling.data_profiler import profile_dataframe, _compute_quality_score

# Create synthetic dataframe to mimic the user's issue
data = {
    'gender': ['M', 'Male', 'm', 'F', 'Female', 'f', 'Male', 'Female', 'M', 'F'],
    'appointment_date': ['2023-01-01', '01/01/2023', 'Jan 1 2023', '2023-01-02', '01/02/2023', 'Jan 2 2023', '2023-01-03', '01/03/2023', 'Jan 3 2023', '2023-01-04'],
    'booking_date': ['2022-12-01', '12/01/2022', 'Dec 1 2022', '2022-12-02', '12/02/2022', 'Dec 2 2022', '2022-12-03', '12/03/2022', 'Dec 3 2022', '2022-12-04'],
    'billing_amount': ['$100', '100.0', ' 100 ', '$200', '200.0', ' 200 ', '$300', '300.0', ' 300 ', '$400'],
    'follow_up_required': ['yes', 'Y', 'Yes', 'no', 'N', 'No', 'yes', 'Y', 'Yes', 'no']
}
df_before = pd.DataFrame(data)

# Transform the dataframe perfectly (as Groq or Gemini would do)
data_after = {
    'gender': ['Male', 'Male', 'Male', 'Female', 'Female', 'Female', 'Male', 'Female', 'Male', 'Female'],
    'appointment_date': ['2023-01-01']*3 + ['2023-01-02']*3 + ['2023-01-03']*3 + ['2023-01-04'],
    'booking_date': ['2022-12-01']*3 + ['2022-12-02']*3 + ['2022-12-03']*3 + ['2022-12-04'],
    'billing_amount': [100.0]*3 + [200.0]*3 + [300.0]*3 + [400.0],
    'follow_up_required': ['Yes', 'Yes', 'Yes', 'No', 'No', 'No', 'Yes', 'Yes', 'Yes', 'No']
}
df_after = pd.DataFrame(data_after)

profile_before = profile_dataframe(df_before)
profile_after = profile_dataframe(df_after)

print(f"Score Before: {profile_before['data_quality_score']}")
print(f"Score After: {profile_after['data_quality_score']}")

# Calculate uniqueness before
u_before = sum(100 - col['unique_pct'] for col in profile_before['columns'].values()) / len(profile_before['columns'])
u_after = sum(100 - col['unique_pct'] for col in profile_after['columns'].values()) / len(profile_after['columns'])

print(f"Uniqueness Penalty Before: {u_before * 0.15}")
print(f"Uniqueness Penalty After: {u_after * 0.15}")

