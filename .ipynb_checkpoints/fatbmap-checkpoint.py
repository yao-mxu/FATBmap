import html
import os
import re

import folium
import leafmap.foliumap as leafmap
import pandas as pd
import streamlit as st
import streamlit_analytics2 as streamlit_analytics

from data_loader import CACHE_FILE, data_signature, load_services

st.set_page_config(layout="wide")

# Make sidebar white with a dark-red title
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
if os.path.exists(logo):
    st.sidebar.image(logo)

# Marker colour (folium.Icon colour name) and legend swatch per category.
CATEGORY_STYLE = {
    "Reproductive Health": {"icon_color": "pink",   "swatch": "#F4A6C0", "icon": "heart"},
    "Mental Health":       {"icon_color": "purple", "swatch": "#7B3FA0", "icon": "comment"},
    "Health Clinics":      {"icon_color": "red",    "swatch": "#D43D3D", "icon": "plus-sign"},
    "Dental":              {"icon_color": "blue",   "swatch": "#3A8DDE", "icon": "star"},
}
DEFAULT_STYLE = {"icon_color": "green", "swatch": "#3C9E4D", "icon": "info-sign"}
MIXED_STYLE = {"icon_color": "gray", "swatch": "#777777", "icon": "th-list"}


# ------------------------------------------------------------------ helpers
@st.cache_data(show_spinner="Loading service data...")
def get_data(signature):
    """`signature` (file modification times) just busts the cache when files change."""
    return load_services()


def md(text) -> str:
    """Make cell text safe/readable in Streamlit markdown ($ would trigger LaTeX)."""
    text = str(text).replace("$", r"\$")
    return text.replace("\n", "  \n")


def link_or_text(text) -> str:
    """Turn any URL on its own line into a markdown link."""
    out = []
    for line in str(text).split("\n"):
        line = line.strip()
        if re.match(r"^https?://\S+$", line):
            out.append(f"[{line}]({line})")
        elif line:
            out.append(md(line))
    return "  \n".join(out)


def is_yes(series: pd.Series) -> pd.Series:
    return series.str.strip().str.lower().str.match(r"^(yes|some)")


def show_field(label: str, value, as_link: bool = False):
    """Show a labelled field only when it has content."""
    value = "" if value is None else str(value).strip()
    if not value:
        return
    st.markdown(f"**{label}**")
    st.markdown(link_or_text(value) if as_link else md(value))


def render_service(row: pd.Series):
    col1, col2 = st.columns(2)
    with col1:
        show_field("Address", row["Addresses"])
        show_field("Website", row["Website"], as_link=True)
        show_field("Phone Number", row["Phone Number"])
        show_field("Fax", row["Fax"])
        show_field("Email", row["Email"])
        show_field("Days of Operation", row["Days of Operation"])
    with col2:
        show_field("Population Served", row["Population Served"])
        show_field("Immigration Status Served", row["Immigration Status Served"])
        show_field("Medicare/Medicaid Accepted?", row["Medicare/Medicaid Accepted?"])
        show_field("Language Offerings", row["Language Offerings?"])
        show_field("Access to Interpreters", row["Access to Interpreters?"])
        show_field("Accepting Referrals/New Patients", row["Accepting Referrals/New Patients?"])

    st.markdown("---")
    show_field("Type of Service", row["Type of Service"])
    show_field("Detailed In-Person Services Provided", row["Detailed In-Person Services Provided"])
    show_field("Telehealth Options", row["Telehealth Options?"])
    show_field("Telehealth Requirements", row["Telehealth Requirements"])
    show_field("Telehealth Services Provided", row["Telehealth Services Provided"])
    show_field("Other Notes", row["Other Notes"])
    show_field("Source", row["Source"], as_link=True)
    show_field("Date Last Updated", row["Date Last Updated"])


def popup_html(group: pd.DataFrame) -> str:
    """One popup per map point; lists every service at that address."""
    parts = [f"<b>{html.escape(group.iloc[0]['address'])}</b>"]
    for _, loc in group.iterrows():
        svc = services_by_id[loc["Service ID"]]
        title = html.escape(svc["Name"])
        label = loc["label"]
        if label and label.lower() != svc["Name"].lower():
            title += f" <i>({html.escape(label)})</i>"
        phone_lines = [p.strip() for p in svc["Phone Number"].split("\n") if p.strip()]
        phone = "<br>".join(html.escape(p) for p in phone_lines[:3])
        block = f"<hr style='margin:6px 0'><b>{title}</b><br>"
        block += f"<span style='color:#666'>{html.escape(svc['Category'])} · {html.escape(svc['County'])} Co.</span><br>"
        if phone:
            block += f"{phone}<br>"
        if svc["Website"].startswith("http"):
            url = html.escape(svc["Website"].split("\n")[0].strip(), quote=True)
            block += f"<a href='{url}' target='_blank'>Website</a>"
        parts.append(block)
    return "<div style='max-height:260px;overflow:auto;font-size:13px'>" + "".join(parts) + "</div>"


def style_for(categories) -> dict:
    cats = set(categories)
    if len(cats) > 1:
        return MIXED_STYLE
    return CATEGORY_STYLE.get(next(iter(cats)), DEFAULT_STYLE)


# ------------------------------------------------------------------ title
st.markdown("## Immigrant Health Services in Santa Clara & San Mateo Counties")

# ============ Wrap main app with analytics ============
with streamlit_analytics.track():
    try:
        services, locations = get_data(data_signature())
        services_by_id = services.set_index("Service ID").to_dict("index")
        services_by_id = {k: {**v} for k, v in services_by_id.items()}

        if not CACHE_FILE.exists():
            st.warning(
                "No `geocode_cache.json` found, so nothing can be placed on the map yet. "
                "Run `python geocode_addresses.py` once (see README) and reload."
            )

        # ============ Sidebar filters ============
        st.sidebar.markdown("---")
        st.sidebar.subheader("Filter services")
        categories = sorted(services["Category"].unique())
        sel_categories = st.sidebar.multiselect("Type of service", categories, default=categories)
        counties = sorted(services["County"].unique())
        sel_counties = st.sidebar.multiselect("County", counties, default=counties)
        query = st.sidebar.text_input("Search", placeholder="e.g. Spanish, free clinic, walk-in")
        only_accepting = st.sidebar.checkbox("Accepting referrals / new patients")
        only_telehealth = st.sidebar.checkbox("Telehealth available")

        mask = services["Category"].isin(sel_categories) & services["County"].isin(sel_counties)
        if query.strip():
            for term in query.lower().split():
                mask &= services["_search"].str.contains(re.escape(term), na=False)
        if only_accepting:
            mask &= is_yes(services["Accepting Referrals/New Patients?"])
        if only_telehealth:
            mask &= is_yes(services["Telehealth Options?"])

        filtered = services[mask]
        f_locations = locations[locations["Service ID"].isin(filtered["Service ID"])]
        mapped = f_locations.dropna(subset=["latitude", "longitude"])

        # ============ Summary numbers ============
        c1, c2, c3 = st.columns(3)
        c1.metric("Services shown", len(filtered))
        c2.metric("Map locations", mapped[["latitude", "longitude"]].drop_duplicates().shape[0])
        c3.metric("Phone / online only (no address)",
                  int((~filtered["Service ID"].isin(f_locations["Service ID"])).sum()))

        # ============ Map ============
        st.subheader("Service Locations Map")
        m = leafmap.Map(center=[37.45, -122.2], zoom=10)

        if not mapped.empty:
            mapped = mapped.assign(_lat=mapped["latitude"].round(5), _lon=mapped["longitude"].round(5))
            for (lat, lon), grp in mapped.groupby(["_lat", "_lon"]):
                style = style_for(grp["Category"])
                n = grp["Service ID"].nunique()
                folium.Marker(
                    [lat, lon],
                    popup=folium.Popup(popup_html(grp), max_width=320),
                    tooltip=grp.iloc[0]["Name"] if n == 1 else f"{n} services at this address",
                    icon=folium.Icon(color=style["icon_color"], icon=style["icon"]),
                ).add_to(m)
            m.fit_bounds([[mapped["latitude"].min(), mapped["longitude"].min()],
                          [mapped["latitude"].max(), mapped["longitude"].max()]])

            legend = " &nbsp; ".join(
                f"<span style='color:{s['swatch']}; font-size:18px'>●</span> {c}"
                for c, s in CATEGORY_STYLE.items() if c in sel_categories
            ) + " &nbsp; <span style='color:#777; font-size:18px'>●</span> Multiple services at one address"
            st.markdown(legend, unsafe_allow_html=True)
        elif CACHE_FILE.exists():
            st.info("No mapped locations match the current filters.")

        m.to_streamlit(height=500)

        # ============ Service details, one tab per category ============
        st.markdown("---")
        if filtered.empty:
            st.info("No services match the current filters.")
        else:
            st.subheader("Service Details")
            present = [c for c in categories if c in set(filtered["Category"])]
            tabs = st.tabs([f"{c} ({(filtered['Category'] == c).sum()})" for c in present])
            for tab, cat in zip(tabs, present):
                with tab:
                    subset = filtered[filtered["Category"] == cat]
                    for _, row in subset.iterrows():
                        with st.expander(f"{row['Name']}  ·  {row['County']} County"):
                            render_service(row)

        # ============ Downloads ============
        st.markdown("---")
        export_cols = [c for c in filtered.columns if not c.startswith("_")]
        d1, d2 = st.columns(2)
        d1.download_button(
            label="Download services as CSV",
            data=filtered[export_cols].to_csv(index=False).encode("utf-8"),
            file_name="immigrant_health_services.csv",
            mime="text/csv",
        )
        d2.download_button(
            label="Download map locations (with coordinates) as CSV",
            data=f_locations.to_csv(index=False).encode("utf-8"),
            file_name="immigrant_health_service_locations.csv",
            mime="text/csv",
        )

        # ============ Data info ============
        with st.expander("Data Information"):
            st.write(f"**Total services in all lists:** {len(services)}")
            st.write(services.groupby(["Category", "County"]).size()
                     .rename("Services").reset_index())
            st.write(f"**Street addresses found:** {len(locations)} "
                     f"(**geocoded:** {int(locations['latitude'].notna().sum())})")
            missing = locations[locations["latitude"].isna()]
            if not missing.empty:
                st.write("**Addresses not on the map yet (run `geocode_addresses.py`):**")
                st.dataframe(missing[["Name", "address"]], hide_index=True)
            no_addr = services[~services["Service ID"].isin(locations["Service ID"])]
            if not no_addr.empty:
                st.write("**Services with no street address (hotlines, online, remote):**")
                st.write(", ".join(no_addr["Name"].tolist()))

    except FileNotFoundError as e:
        st.error(f"Data file not found: {e}. Make sure the CSVs are in the `data` folder next to this script.")
    except Exception as e:
        st.error(f"Error loading data: {e}")

    # Show source code
    with st.expander("See github repository"):
        st.code(""" "https://github.com/yao-mxu/FATBmap"
        """, language="python")
