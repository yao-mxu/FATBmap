import streamlit as st
import streamlit_analytics2 as streamlit_analytics
import leafmap.foliumap as leafmap
import pandas as pd
import json
import requests
from io import StringIO
import os
import time

st.set_page_config(layout="wide")

# Make sidebar completely transparent
st.markdown("""
<style>
[data-testid="stSidebar"] {
    background: white !important;
}
[data-testid="stSidebar"] > div:first-child {
    background: white !important;
}
[data-testid="stSidebar"] h1 {
    color: #8B0000 !important;
    background: transparent !important;
}
[data-testid="stSidebar"] .stMarkdown {
    background: white !important;
    padding: 10px !important;
}
</style>
""", unsafe_allow_html=True)

markdown = """
<https://globalhealth.stanford.edu/programs/families-at-the-border/>
"""

st.sidebar.title("Families at the Border Team")
st.sidebar.info(markdown)
logo = "GlobalHealth.png"
st.sidebar.image(logo)

st.markdown("## Immigrant Health Services in Santa Clara & San Mateo Counties")

# ============ Wrap your main app with analytics ============
with streamlit_analytics.track():
    # ============ Load the geocoded CSV data ============
    csv_file = "geocoded_services.csv"

    try:
        # Read the CSV
        df_services = pd.read_csv(csv_file)
        
        # Clean column names: strip leading/trailing spaces
        df_services.columns = df_services.columns.str.strip()
           
        # Filter out rows without coordinates for the map
        df_with_coords = df_services.dropna(subset=['latitude', 'longitude'])
        
        # ============ Create Map ============
        st.subheader("Service Locations Map")
        
        # Create map centered on San Mateo County
        m = leafmap.Map(center=[37.5, -122.3], zoom=11)
        
        # Add points from the geocoded services
        if not df_with_coords.empty:
            # Add markers with popups
            for idx, row in df_with_coords.iterrows():
                # Clean up phone number for display
                phone = row.get('Phone Number', 'N/A')
                if pd.isna(phone) or phone == '':
                    phone = 'N/A'
                
                popup_text = f"""
                <b>{row.get('Name', 'N/A')}</b><br>
                <b>Address:</b> {row.get('Addresses', 'N/A')}<br>
                <b>Phone:</b> {phone}<br>
                <b>Services:</b> {row.get('Type of Service', 'N/A')}
                """
                m.add_marker(
                    [row['latitude'], row['longitude']],
                    popup=popup_text,
                    icon_name="hospital"
                )
            
            st.success(f"Showing {len(df_with_coords)} service locations on the map")
        else:
            st.warning("No locations with coordinates found. Please check the data.")
        
        # Display the map
        m.to_streamlit(height=500)
        
        # ============ Display service details ============
        st.markdown("---")
        
        # Display count of service providers
        st.info(f"Showing {len(df_services)} service providers in total")
     
        st.subheader("Reproductive Health Services in San Mateo County")
        
        # Display each service in its own expander
        for idx, row in df_services.iterrows():
            service_name = row.get('Name', f'Service {idx+1}')
            with st.expander(f"{service_name}"):
                # Create two columns for better organization
                col1, col2 = st.columns(2)
                
                with col1:
                    st.markdown("**Address**")
                    st.write(row.get('Addresses', 'N/A'))
                    st.write("")
                    
                    st.markdown("**Website**")
                    st.write(row.get('Website', 'N/A'))
                    st.write("")
                    
                    st.markdown("**Phone Number**")
                    st.write(row.get('Phone Number', 'N/A'))
                    st.write("")
                    
                    st.markdown("**Fax**")
                    st.write(row.get('Fax', 'N/A'))
                    st.write("")
                    
                    st.markdown("**Email**")
                    st.write(row.get('Email', 'N/A'))
                
                with col2:
                    st.markdown("**Days of Operation**")
                    st.write(row.get('Days of Operation', 'N/A'))
                    st.write("")
                    
                    st.markdown("**Population Served**")
                    st.write(row.get('Population Served', 'N/A'))
                    st.write("")
                    
                    st.markdown("**Immigration Status Served**")
                    st.write(row.get('Immigration Status Served', 'N/A'))
                    st.write("")
                    
                    st.markdown("**Medicare/Medicaid Accepted**")
                    st.write(row.get('Medicare/Medicaid Accepted?', 'N/A'))
                    st.write("")
                    
                    st.markdown("**Language Offerings**")
                    st.write(row.get('Language Offerings?', 'N/A'))
                
                # Full width sections
                st.markdown("---")
                
                st.markdown("**Access to Interpreters**")
                st.write(row.get('Access to Interpreters?', 'N/A'))
                st.write("")
                
                st.markdown("**Type of Service**")
                st.write(row.get('Type of Service', 'N/A'))
                st.write("")
                
                st.markdown("**Detailed In-Person Services Provided**")
                st.write(row.get('Detailed In-Person Services Provided', 'N/A'))
                st.write("")
                
                st.markdown("**Telehealth Options**")
                st.write(row.get('Telehealth Options?', 'N/A'))
                st.write("")
                
                if pd.notna(row.get('If YES to telehealth: any requirements to accessing services?')):
                    st.markdown("**Telehealth Requirements**")
                    st.write(row.get('If YES to telehealth: any requirements to accessing services?', 'N/A'))
                    st.write("")
                
                if pd.notna(row.get('If YES to previous: Telehealth Services Provided?')):
                    st.markdown("**Telehealth Services Provided**")
                    st.write(row.get('If YES to previous: Telehealth Services Provided?', 'N/A'))
                    st.write("")
                
                st.markdown("**Accepting Referrals/New Patients**")
                st.write(row.get('Accepting Referrals/New Patients?', 'N/A'))
                st.write("")
                
                if pd.notna(row.get('Other Notes')):
                    st.markdown("**Other Notes**")
                    st.write(row.get('Other Notes', 'N/A'))
                    st.write("")
                
                st.markdown("**Date Last Updated**")
                st.write(row.get('Date Last Updated', 'N/A'))
                
                # Show coordinates if available
                if pd.notna(row.get('latitude')) and pd.notna(row.get('longitude')):
                    st.markdown("**Coordinates**")
                    st.write(f"{row['latitude']:.6f}, {row['longitude']:.6f}")
        
        # Download button
        csv_download = df_services.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="Download all data as CSV",
            data=csv_download,
            file_name="reproductive_health_services_with_coords.csv",
            mime="text/csv",
        )
        
        # Show data info
        with st.expander("Data Information"):
            st.write(f"**Total providers:** {len(df_services)}")
            st.write(f"**Providers with coordinates:** {len(df_with_coords)}")
            st.write("**Columns available:**")
            st.write(", ".join(df_services.columns.tolist()))
                        
    except FileNotFoundError:
        st.error(f"CSV file '{csv_file}' not found. Please make sure it's in the same folder as your script.")
        st.info("Expected file location: Same folder as this script")
    except Exception as e:
        st.error(f"Error loading data: {e}")

    # Show source code
    with st.expander("See github repository"):
        st.code(""" "https://github.com/yao-mxu/FATBmap"
        """, language="python")