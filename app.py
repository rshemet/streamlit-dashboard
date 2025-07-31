import streamlit as st
import pandas as pd
import altair as alt
import os
from supabase import create_client, Client
from dotenv import load_dotenv

prod_values_to_filter_out = ['kin_ai', 'cactus_chat', 'other']

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

col_filter1, col_filter2 = st.columns(2)

with col_filter1:
    included_projects = st.multiselect(
        "Select projects to include:", 
        options=prod_values_to_filter_out, 
        default=['other']
    )

with col_filter2:
    group_by = st.selectbox(
        "Group by:",
        options=['project', 'device', 'event (NEW!) ⭐'],
        index=0
    )
    # Clean the group_by value for internal use
    if group_by.startswith('event'):
        group_by = 'event'

filter_out_projects = [p for p in prod_values_to_filter_out if p not in included_projects]
params = {"filter_out_projects": filter_out_projects}

# Load data based on group_by selection
if group_by == 'project':
    rates_data = run_sql_snippet('get_project_error_rate', params=params)
    count_field = 'projects'
    chart_suffix = '(by Project)'
elif group_by == 'device':
    st.warning("⚠️ **Watch out:** there is a known issue with telemetry, which **does not** log device ID in error logs. This leads to misleadingly low error rates. \n\nGroup errors **by event** for a more accurate representation.")
    rates_data = run_sql_snippet('get_device_error_rate', params=params)
    count_field = 'devices'
    chart_suffix = '(by Device)'
else:  # event
    rates_data = run_sql_snippet('get_event_error_rate', params=params)
    count_field = 'events'
    chart_suffix = '(by Event)'

if not rates_data.empty:
    rates_data.rename(columns={'t': 'time'}, inplace=True)
    rates_data['time'] = pd.to_datetime(rates_data['time'])
    counts_data = rates_data
    success_rate_data = rates_data
    error_rate_data = rates_data
else:
    st.warning(f"Could not load {group_by} rates. Using sample data.")


cumulative_tokens = run_sql_snippet('get_generated_tokens_new', params=params)
if not cumulative_tokens.empty:
    # Adapt to the new data format
    cumulative_tokens.rename(columns={'t': 'time'}, inplace=True)
    cumulative_tokens['time'] = pd.to_datetime(cumulative_tokens['time'])

    # Densify the data to fix gaps in the cumulative chart
    # Create a complete grid of dates and devices
    date_range = pd.date_range(start=cumulative_tokens['time'].min(), end=cumulative_tokens['time'].max(), freq='D')
    all_devices = cumulative_tokens['device_manufacturer'].unique()
    grid = pd.MultiIndex.from_product([date_range, all_devices], names=['time', 'device_manufacturer']).to_frame(index=False)

    # Sum up tokens per day/device in case there are multiple entries
    daily_tokens = cumulative_tokens.groupby(['time', 'device_manufacturer'])['tokens_generated'].sum().reset_index()

    # Merge with the grid to fill in missing data
    merged_df = pd.merge(grid, daily_tokens, on=['time', 'device_manufacturer'], how='left').fillna(0)

    # Sort by device and time, then calculate the true cumulative sum
    merged_df.sort_values(['device_manufacturer', 'time'], inplace=True)
    merged_df['cumulative_tokens'] = merged_df.groupby('device_manufacturer')['tokens_generated'].cumsum()
    cumulative_tokens = merged_df
else:
    st.warning("Could not load cumulative tokens. Using sample data.")


error_logs = run_sql_snippet('get_error_logs', params=params)
if error_logs.empty:
    st.warning("Could not load error logs. Using sample data.")

# --- Row 1: Daily Counts ---
st.header(f"Daily {group_by.title()} Count")
chart1 = create_stacked_bar_chart(counts_data, 'time', count_field, 'framework', f'Daily {group_by.title()} Count', f'{group_by.title()} Count')
if chart1:
    st.altair_chart(chart1, use_container_width=True)

# --- Row 2: Success Rate ---
st.header(f"Success Rate {chart_suffix}")
chart2 = create_line_chart(success_rate_data, 'time', 'success_rate', 'framework', f'Daily Success Rate {chart_suffix}', 'Success Rate (%)', y_axis_format='%')
if chart2:
    st.altair_chart(chart2, use_container_width=True)

# --- Row 3: Error Rate ---
st.header(f"Error Rate {chart_suffix}")
chart3 = create_line_chart(error_rate_data, 'time', 'error_rate', 'framework', f'Daily Error Rate {chart_suffix}', 'Error Rate (%)', y_axis_format='%')
if chart3:
    st.altair_chart(chart3, use_container_width=True)


# --- Row 4: Cumulative Tokens ---
st.header("Total Tokens Generated")
if not cumulative_tokens.empty:
    chart4 = alt.Chart(cumulative_tokens).mark_bar().encode(
        x=alt.X('time:T', timeUnit='yearmonthdate', title='Time', axis=alt.Axis(format='%b %d')),
        y=alt.Y('tokens_generated:Q', title='Tokens Generated', stack=True),
        color=alt.Color('device_manufacturer:N', legend=alt.Legend(title="Device Manufacturer")),
        tooltip=[
            'time',
            'device_manufacturer',
            alt.Tooltip('tokens_generated:Q', title='Tokens Generated')
        ]
    ).properties(
        title='Daily Tokens Generated'
    ).interactive()
    st.altair_chart(chart4, use_container_width=True)
else:
    st.warning("No data for Tokens Generated chart.")


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