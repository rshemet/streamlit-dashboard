import streamlit as st
import pandas as pd
import altair as alt
import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

# --- Page Configuration ---
st.set_page_config(
    page_title="Cactus Performance Dashboard",
    page_icon="🌵",
    layout="wide",
)

# --- Supabase Connection ---
# The user needs to add these to .streamlit/secrets.toml
# See: https://docs.streamlit.io/connections/secrets-management
try:
    url = st.secrets["supabase"]["supabase_url"]
    key = st.secrets["supabase"]["supabase_key"]
    supabase: Client = create_client(url, key)
except KeyError:
    st.error("Supabase credentials not found. Please add them to your `.streamlit/secrets.toml` file.")
    st.info("Your `.streamlit/secrets.toml` file should look like this:")
    st.code("""
[supabase]
supabase_url = "YOUR_SUPABASE_URL"
supabase_key = "YOUR_SUPABASE_KEY"
    """)
    st.stop()
except Exception as e:
    st.error(f"An error occurred while connecting to Supabase: {e}")
    st.stop()


# --- Helper Functions ---
@st.cache_data(ttl=600)  # Cache for 10 minutes
def run_sql_snippet(snippet_name: str, params: dict = None):
    """Runs a SQL snippet from Supabase."""
    try:
        # Supabase Python library uses RPC to call PostgreSQL functions
        if params:
            data = supabase.rpc(snippet_name, params).execute()
        else:
            data = supabase.rpc(snippet_name, {}).execute()
        
        return pd.DataFrame(data.data)
    except Exception as e:
        st.error(f"Error running snippet '{snippet_name}': {e}")
        return pd.DataFrame()

def create_stacked_bar_chart(df, time_col, value_col, category_col, title, y_axis_title, y_axis_format=None):
    """Creates a stacked bar chart using Altair."""
    if df.empty:
        st.warning(f"No data for: {title}")
        return None

    y_encoding = alt.Y(f'sum({value_col}):Q', title=y_axis_title)
    if y_axis_format:
        y_encoding.axis = alt.Axis(format=y_axis_format)

    chart = alt.Chart(df).mark_bar().encode(
        x=alt.X(f'{time_col}:T', timeUnit='yearmonthdate', title='Time', axis=alt.Axis(format='%b %d')),
        y=y_encoding,
        color=alt.Color(f'{category_col}:N', legend=alt.Legend(title="Framework")),
        tooltip=[time_col, f'sum({value_col})', category_col]
    ).properties(
        title=title
    ).interactive()
    return chart

def create_line_chart(df, time_col, value_col, category_col, title, y_axis_title, y_axis_format=None):
    """Creates a line chart using Altair."""
    if df.empty:
        st.warning(f"No data for: {title}")
        return None

    y_encoding = alt.Y(f'{value_col}:Q', title=y_axis_title)
    if y_axis_format:
        y_encoding.axis = alt.Axis(format=y_axis_format)

    chart = alt.Chart(df).mark_line().encode(
        x=alt.X(f'{time_col}:T', timeUnit='yearmonthdate', title='Time', axis=alt.Axis(format='%b %d')),
        y=y_encoding,
        color=alt.Color(f'{category_col}:N', legend=alt.Legend(title="Framework")),
        tooltip=[time_col, value_col, category_col]
    ).properties(
        title=title
    ).interactive()
    return chart

# --- Main Dashboard ---
st.title("Cactus Performance Dashboard 🌵")

st.markdown("""
This dashboard visualizes daily performance metrics for Cactus.
""")

# Load project rates from a single snippet
project_rates = run_sql_snippet('get_project_error_rate')
if not project_rates.empty:
    project_rates.rename(columns={'t': 'time'}, inplace=True)
    project_rates['time'] = pd.to_datetime(project_rates['time'])
    project_counts = project_rates
    success_rate_project = project_rates
    error_rate_project = project_rates
else:
    st.warning("Could not load project rates. Using sample data.")

# Load device rates from a single snippet since it contains both success and error rates
device_rates = run_sql_snippet('get_device_error_rate')
if not device_rates.empty:
    device_rates.rename(columns={'t': 'time'}, inplace=True)
    device_rates['time'] = pd.to_datetime(device_rates['time'])
    success_rate_device = device_rates
    error_rate_device = device_rates
    device_counts = device_rates
else:
    st.warning("Could not load device rates. Using sample data for device counts, success and error rates.")


cumulative_tokens = run_sql_snippet('get_generated_tokens_new')
if not cumulative_tokens.empty:
    # Adapt to the new data format
    cumulative_tokens.rename(columns={'t': 'time'}, inplace=True)
    cumulative_tokens['time'] = pd.to_datetime(cumulative_tokens['time'])

    # Densify the data to fix gaps in the cumulative chart
    # Create a complete grid of dates and devices
    date_range = pd.date_range(start=cumulative_tokens['time'].min(), end=cumulative_tokens['time'].max(), freq='D')
    all_devices = cumulative_tokens['device'].unique()
    grid = pd.MultiIndex.from_product([date_range, all_devices], names=['time', 'device']).to_frame(index=False)

    # Sum up tokens per day/device in case there are multiple entries
    daily_tokens = cumulative_tokens.groupby(['time', 'device'])['tokens_generated'].sum().reset_index()

    # Merge with the grid to fill in missing data
    merged_df = pd.merge(grid, daily_tokens, on=['time', 'device'], how='left').fillna(0)

    # Sort by device and time, then calculate the true cumulative sum
    merged_df.sort_values(['device', 'time'], inplace=True)
    merged_df['cumulative_tokens'] = merged_df.groupby('device')['tokens_generated'].cumsum()
    cumulative_tokens = merged_df
else:
    st.warning("Could not load cumulative tokens. Using sample data.")


error_logs = run_sql_snippet('get_error_logs')
if error_logs.empty:
    st.warning("Could not load error logs. Using sample data.")

# --- Row 1 ---
st.header("Daily Project and Device Counts")
col1a, col1b = st.columns(2)

with col1a:
    chart1a = create_stacked_bar_chart(project_counts, 'time', 'projects', 'framework', 'Daily Project Count', 'Project Count')
    if chart1a:
        st.altair_chart(chart1a, use_container_width=True)

with col1b:
    chart1b = create_stacked_bar_chart(device_counts, 'time', 'devices', 'framework', 'Daily Device Count', 'Device Count')
    if chart1b:
        st.altair_chart(chart1b, use_container_width=True)

# --- Row 2 ---
st.header("Success Rate")
col2a, col2b = st.columns(2)

with col2a:
    chart2a = create_line_chart(success_rate_project, 'time', 'success_rate', 'framework', 'Daily Success Rate (by Project)', 'Success Rate (%)', y_axis_format='%')
    if chart2a:
        st.altair_chart(chart2a, use_container_width=True)
with col2b:
    chart2b = create_line_chart(success_rate_device, 'time', 'success_rate', 'framework', 'Daily Success Rate (by Device)', 'Success Rate (%)', y_axis_format='%')
    if chart2b:
        st.altair_chart(chart2b, use_container_width=True)

# --- Row 3 ---
st.header("Error Rate")
col3a, col3b = st.columns(2)

with col3a:
    chart3a = create_line_chart(error_rate_project, 'time', 'error_rate', 'framework', 'Daily Error Rate (by Project)', 'Error Rate (%)', y_axis_format='%')
    if chart3a:
        st.altair_chart(chart3a, use_container_width=True)
with col3b:
    chart3b = create_line_chart(error_rate_device, 'time', 'error_rate', 'framework', 'Daily Error Rate (by Device)', 'Error Rate (%)', y_axis_format='%')
    if chart3b:
        st.altair_chart(chart3b, use_container_width=True)


# --- Row 4: Cumulative Tokens ---
st.header("Cumulative Tokens Generated")
if not cumulative_tokens.empty:
    chart4 = alt.Chart(cumulative_tokens).mark_area().encode(
        x=alt.X('time:T', title='Time', axis=alt.Axis(format='%b %d')),
        y=alt.Y('cumulative_tokens:Q', title='Cumulative Tokens'),
        color=alt.Color('device:N', legend=alt.Legend(title="Device")),
        tooltip=['time', 'device', 'tokens_generated', 'cumulative_tokens']
    ).properties(
        title='Tokens Generated, Cumulative Over Time'
    ).interactive()
    st.altair_chart(chart4, use_container_width=True)
else:
    st.warning("No data for Cumulative Tokens chart.")


# --- Row 5: Raw Error Logs ---
st.header("Raw Error Logs")
if not error_logs.empty:
    for index, row in error_logs.iterrows():
        payload = row.get('error_payload', {})
        message = payload.get('message', 'No message found')
        framework = row.get('framework', 'N/A')
        error_count = row.get('errors', 'N/A')
        last_seen_summary = row.get('last_seen_summary', 'N/A')

        expander_title = f"[{framework.upper()}] {message} | Count: {error_count} | Last seen: {last_seen_summary}"
        
        with st.expander(expander_title):
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Framework", framework)
            with col2:
                st.metric("Count", error_count)

            st.metric("Last Seen", row.get('last_seen', 'N/A'))
            st.caption(f"First seen: {row.get('first_seen', 'N/A')}")

            stack = payload.get('stack')
            if stack:
                st.code(stack, language='text')
            else:
                st.info("No stack trace available for this error.")
else:
    st.warning("No error logs to display.")

st.sidebar.info("""
**To run this app:**
1. Install dependencies: `pip install -r requirements.txt`
2. Create `.streamlit/secrets.toml` with your Supabase credentials.
3. Run from your terminal: `streamlit run app.py`
""") 