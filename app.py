import html
import re
import textwrap
from datetime import datetime, timezone

import pandas as pd
import pytz
import requests
import streamlit as st

# -----------------------------
# CONFIG
# -----------------------------

API_KEY = st.secrets["YOUTUBE_API_KEY"]
YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"
CATEGORY_NEWS_POLITICS = "25"   # News & Politics category

# Region codes we’ll support (you can add more later)
REGIONS = {
    "Worldwide (sampled)": ["US", "CA", "GB", "AU", "IN", "DE", "FR", "BR", "JP", "ZA"],
    "North America": ["US", "CA", "MX"],
    "Europe core": ["GB", "DE", "FR", "IT", "ES", "NL", "SE"],
    "Asia-Pacific": ["IN", "JP", "KR", "AU", "SG", "ID"],
}

ALL_REGION_CODES = sorted(
    set(code for codes in REGIONS.values() for code in codes)
)

# A human-readable label for each individual country code
REGION_LABELS = {
    "US": "United States",
    "CA": "Canada",
    "GB": "United Kingdom",
    "AU": "Australia",
    "IN": "India",
    "DE": "Germany",
    "FR": "France",
    "BR": "Brazil",
    "JP": "Japan",
    "ZA": "South Africa",
    "MX": "Mexico",
    "IT": "Italy",
    "ES": "Spain",
    "NL": "Netherlands",
    "SE": "Sweden",
    "KR": "South Korea",
    "SG": "Singapore",
    "ID": "Indonesia",
}

# -----------------------------
# Helper functions
# -----------------------------


def yt_get(endpoint: str, params: dict) -> dict:
    params = {**params, "key": API_KEY}
    resp = requests.get(
        f"{YOUTUBE_API_BASE}/{endpoint}", params=params, timeout=20
    )
    resp.raise_for_status()
    return resp.json()


def parse_iso8601_duration(duration_str: str) -> int:
    """Very small ISO-8601 duration parser for PT#H#M#S -> seconds."""
    if not duration_str:
        return 0

    pattern = re.compile(
        r"P"
        r"(?:(?P<days>\d+)D)?"
        r"(?:T"
        r"(?:(?P<hours>\d+)H)?"
        r"(?:(?P<minutes>\d+)M)?"
        r"(?:(?P<seconds>\d+)S)?"
        r")?"
    )
    m = pattern.fullmatch(duration_str)
    if not m:
        return 0

    days = int(m.group("days") or 0)
    hours = int(m.group("hours") or 0)
    minutes = int(m.group("minutes") or 0)
    seconds = int(m.group("seconds") or 0)
    total = (((days * 24 + hours) * 60) + minutes) * 60 + seconds
    return total


def format_views(views: int) -> str:
    if views is None:
        return "–"
    v = int(views)
    if v >= 1_000_000:
        return f"{v/1_000_000:.1f}M"
    if v >= 1_000:
        return f"{v/1_000:.1f}K"
    return f"{v:,}"


def format_duration(seconds: int) -> str:
    if not seconds:
        return "–"
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:d}:{s:02d}"


def format_age(published_at: datetime) -> str:
    now = datetime.now(timezone.utc)
    delta = now - published_at
    days = delta.days
    seconds = delta.seconds
    if days > 7:
        weeks = days // 7
        return f"{weeks} week{'s' if weeks != 1 else ''} ago"
    if days >= 1:
        return f"{days} day{'s' if days != 1 else ''} ago"
    hours = seconds // 3600
    if hours >= 1:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    minutes = (seconds % 3600) // 60
    if minutes >= 1:
        return f"{minutes} min ago"
    return "just now"


# -----------------------------
# Fetch data
# -----------------------------


@st.cache_data(ttl=60 * 60 * 2, show_spinner=True)
def fetch_trending_for_region(region_code: str) -> pd.DataFrame:
    """
    Fetch top News & Politics trending videos for a single region.
    """
    params = {
        "part": "snippet,statistics,contentDetails",
        "chart": "mostPopular",
        "regionCode": region_code,
        "videoCategoryId": CATEGORY_NEWS_POLITICS,
        "maxResults": 50,
    }
    data = yt_get("videos", params)
    items = data.get("items", [])

    videos = []
    for item in items:
        vid = item["id"]
        snip = item.get("snippet", {})
        stats = item.get("statistics", {})
        details = item.get("contentDetails", {})

        title = snip.get("title", "")
        desc = snip.get("description", "") or ""
        channel_title = snip.get("channelTitle", "")
        published_at_str = snip.get("publishedAt")
        published_at = (
            datetime.fromisoformat(published_at_str.replace("Z", "+00:00"))
            if published_at_str
            else datetime.now(timezone.utc)
        )

        duration = parse_iso8601_duration(details.get("duration", ""))
        try:
            views = int(stats.get("viewCount", 0))
        except Exception:
            views = 0

        thumbs = snip.get("thumbnails", {})
        thumb_obj = (
            thumbs.get("medium")
            or thumbs.get("high")
            or thumbs.get("default")
            or {}
        )
        thumb_url = thumb_obj.get("url")

        url = f"https://www.youtube.com/watch?v={vid}"

        videos.append(
            {
                "region_code": region_code,
                "region_name": REGION_LABELS.get(region_code, region_code),
                "video_id": vid,
                "title": title,
                "description": desc,
                "channel_title": channel_title,
                "published_at": published_at,
                "duration_sec": duration,
                "view_count": views,
                "thumbnail_url": thumb_url,
                "url": url,
            }
        )

    return pd.DataFrame(videos)


@st.cache_data(ttl=60 * 60 * 2, show_spinner=True)
def fetch_multi_region(region_codes: list[str]) -> tuple[pd.DataFrame, datetime]:
    """
    Fetch for many regions and combine into one DataFrame.
    """
    all_dfs = []
    for code in region_codes:
        df_region = fetch_trending_for_region(code)
        if not df_region.empty:
            all_dfs.append(df_region)

    if all_dfs:
        combined = pd.concat(all_dfs, ignore_index=True)
    else:
        combined = pd.DataFrame()

    fetched_at_utc = datetime.now(timezone.utc)
    return combined, fetched_at_utc


# -----------------------------
# UI Styling
# -----------------------------


def render_css():
    st.markdown(
        """
<style>
html, body {
  background-color: #02030a !important;
}
.stApp {
  background: radial-gradient(circle at top, #202642 0, #050711 45%, #02030a 100%) !important;
  color: #ffffff;
  font-family: system-ui, -apple-system, BlinkMacSystemFont, "SF Pro Text", "Inter", sans-serif;
}
header[data-testid="stHeader"] {
  background: transparent !important;
}
div[data-testid="stDecoration"] {
  background: transparent !important;
}
.block-container {
  padding-top: 1.2rem;
  padding-bottom: 2rem;
  max-width: 1200px;
}

/* Tabs as bubbles */
.stTabs [data-baseweb="tab-list"] {
  gap: 0.35rem;
  border-bottom: none !important;
}
.stTabs [data-baseweb="tab"] {
  background-color: #080b16;
  border-radius: 999px;
  padding: 0.4rem 1.0rem;
  font-size: 0.9rem;
  font-weight: 650;
  color: #c4cff5;
  border: 1px solid transparent;
}
.stTabs [data-baseweb="tab"][aria-selected="true"] {
  background: linear-gradient(135deg, #ff4b4b, #ff9f43);
  color: #ffffff;
  border-color: rgba(255,255,255,0.16);
}
.stTabs [data-baseweb="tab-highlight"] {
  background: transparent !important;
  border-bottom: none !important;
}

/* Buttons */
.stButton button {
  border-radius: 999px;
  padding: 0.35rem 0.9rem;
  font-size: 0.85rem;
  border: none;
  background: linear-gradient(135deg, #ff4b4b, #ff9f43);
  color: #ffffff;
  box-shadow: 0 8px 18px rgba(0,0,0,0.45);
  transition: transform 0.12s ease, box-shadow 0.12s ease, filter 0.12s ease;
}
.stButton button:hover {
  filter: brightness(1.05);
  transform: translateY(-1px);
  box-shadow: 0 12px 28px rgba(0,0,0,0.65);
}

/* Hero section */
.hero {
  position: relative;
  border-radius: 14px;
  padding: 18px 20px;
  margin-bottom: 14px;
  background: radial-gradient(circle at top left, #2a314c 0, #141726 45%, #050711 100%);
  box-shadow: 0 14px 35px rgba(0,0,0,0.7);
}
.hero-title {
  font-size: 26px;
  font-weight: 680;
  letter-spacing: .03em;
}
.hero-sub {
  font-size: 14px;
  max-width: 900px;
  line-height: 1.6;
}

/* Region chips */
.region-chip {
  display: inline-flex;
  align-items: center;
  padding: 0.25rem 0.75rem;
  border-radius: 999px;
  background: rgba(255,255,255,0.06);
  margin: 2px 4px;
  font-size: 0.8rem;
}

/* Video cards */
.video-card {
  border-radius: 14px;
  padding: 12px 14px;
  margin-bottom: 8px;
  background: radial-gradient(circle at top left, #20263b 0, #111522 60%, #090b14 100%);
  border: 1px solid rgba(255,255,255,0.05);
  transition: background-color 0.18s ease, transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
}
.video-card:hover {
  background: radial-gradient(circle at top left, #323b5c 0, #151a2a 60%, #0b0f1b 100%);
  box-shadow: 0 16px 38px rgba(0,0,0,0.75);
  transform: translateY(-2px);
  border-color: rgba(255,255,255,0.12);
}
.video-thumb img {
  border-radius: 10px;
  display: block;
}
.video-meta {
  font-size: 12px;
  color: #c9d3f5;
}
.video-desc {
  font-size: 13px;
  color: #e0e0e0;
}
</style>
        """,
        unsafe_allow_html=True,
    )


def render_hero(fetched_at_utc: datetime, chosen_regions: list[str]):
    eastern = pytz.timezone("US/Eastern")
    fetched_et = fetched_at_utc.astimezone(eastern)
    fetched_str = fetched_et.strftime("%b %d, %Y • %I:%M %p ET")

    pretty_regions = ", ".join(
        REGION_LABELS.get(code, code) for code in chosen_regions
    )

    st.markdown(
        textwrap.dedent(
            f"""
<div class="hero">
  <div class="hero-title">Global YouTube News &amp; Politics – Trending Watch</div>
  <div class="hero-sub" style="margin-top:6px;">
    Tracking <b>News &amp; Politics</b> videos from YouTube’s trending charts in multiple
    regions. View counts shown here are <b>global</b> per video; YouTube does not expose
    per-country viewership, so this is a cross-region look at what’s rising on the
    platform.
  </div>
  <div style="margin-top:10px;font-size:13px;color:#e9eefc;">
    <span style="padding:5px 11px;border-radius:999px;background:rgba(0,0,0,0.45);">
      ⏱ Last fetched: <b>{fetched_str}</b>
    </span>
  </div>
  <div style="margin-top:8px;font-size:12px;color:#c4c9ea;">
    Regions in this view:
    {" ".join(
        f'<span class="region-chip">{html.escape(REGION_LABELS.get(c,c))}</span>'
        for c in chosen_regions
    )}
  </div>
</div>
            """
        ),
        unsafe_allow_html=True,
    )


def render_video_card(row, rank: int | None = None):
    title = row["title"]
    url = row["url"]
    thumb = row["thumbnail_url"]
    views = int(row["view_count"])
    duration = format_duration(int(row["duration_sec"]))
    age = format_age(row["published_at"])
    channel = row["channel_title"]
    region_name = row["region_name"]

    views_str = format_views(views)

    rank_label = f"#{rank}" if rank is not None else ""
    card_html = textwrap.dedent(
        f"""
<div class="video-card">
  <div style="display:flex;gap:14px;align-items:flex-start;">
    <div class="video-thumb" style="flex:0 0 200px;">
      <a href="{html.escape(url)}" target="_blank" rel="noopener noreferrer">
        <img src="{thumb}" alt="thumbnail">
      </a>
    </div>
    <div style="flex:1;min-width:0;">
      <div style="font-size:12px;color:#9ba4c9;margin-bottom:2px;">{html.escape(region_name)} {rank_label}</div>
      <a href="{html.escape(url)}" target="_blank" rel="noopener noreferrer"
         style="font-size:16px;font-weight:600;color:#e5f0ff;text-decoration:none;">
        {html.escape(title)}
      </a>
      <div class="video-meta" style="margin-top:4px;">
        👁 {views_str} &nbsp; ⏱ {duration} &nbsp; 🕒 {age}
      </div>
      <div style="margin-top:3px;font-size:13px;color:#c4c9ea;">
        {html.escape(channel)}
      </div>
    </div>
  </div>
</div>
        """
    )
    st.markdown(card_html, unsafe_allow_html=True)


# -----------------------------
# Main app
# -----------------------------


def main():
    st.set_page_config(
        page_title="Global YouTube News & Politics – Trending Watch",
        layout="wide",
    )
    render_css()

    # Top bar: preset + custom region selection
    left, right = st.columns([2, 3])
    with left:
        preset = st.selectbox(
            "Region preset",
            list(REGIONS.keys()) + ["Custom selection…"],
            index=0,
        )
    if preset == "Custom selection…":
        with right:
            chosen_regions = st.multiselect(
                "Choose individual countries / regions",
                options=ALL_REGION_CODES,
                default=["US", "GB", "IN"],
                format_func=lambda c: REGION_LABELS.get(c, c),
            )
    else:
        chosen_regions = REGIONS[preset]
        with right:
            st.write("Regions in preset:")
            st.write(
                ", ".join(REGION_LABELS.get(c, c) for c in chosen_regions)
            )

    if not chosen_regions:
        st.warning("Select at least one region to fetch trending videos.")
        return

    refresh_col, _ = st.columns([1, 4])
    with refresh_col:
        if st.button("🔄 Refresh data"):
            st.cache_data.clear()
            st.rerun()

    df, fetched_at_utc = fetch_multi_region(chosen_regions)

    if df.empty:
        st.error("No data returned from the YouTube API.")
        return

    render_hero(fetched_at_utc, chosen_regions)

    # Tabs
    t_by_region, t_global, t_table = st.tabs(
        ["By region", "Combined “global” ranking", "Raw table"]
    )

    # --- By Region tab ---
    with t_by_region:
        st.markdown(
            "### Per-region top News & Politics videos\n"
            "For each region, the videos below come from that country’s **trending "
            "chart** in the News & Politics category (ID 25), ranked by view count."
        )
        for code in chosen_regions:
            sub = df[df["region_code"] == code].copy()
            if sub.empty:
                continue
            sub = sub.sort_values("view_count", ascending=False)
            region_name = REGION_LABELS.get(code, code)
            st.markdown(f"#### {region_name}")
            for idx, row in sub.head(10).reset_index(drop=True).iterrows():
                render_video_card(row, rank=idx + 1)
            st.markdown("---")

    # --- Combined tab ---
    with t_global:
        st.markdown(
            "### Combined “global” ranking across selected regions\n"
            "All selected regions merged together and ranked by **current view count**. "
            "A single video might appear multiple times if it trends in more than one region."
        )
        df_global = df.sort_values("view_count", ascending=False)
        for idx, row in df_global.head(30).reset_index(drop=True).iterrows():
            render_video_card(row, rank=idx + 1)

    # --- Raw table tab ---
    with t_table:
        st.markdown("### Raw data table")
        df_show = df.copy()
        df_show["published_at"] = df_show["published_at"].dt.tz_convert("US/Eastern")
        df_show = df_show.rename(
            columns={
                "duration_sec": "duration_s",
            }
        )
        st.dataframe(
            df_show[
                [
                    "region_code",
                    "region_name",
                    "title",
                    "channel_title",
                    "view_count",
                    "duration_s",
                    "published_at",
                    "url",
                ]
            ],
            use_container_width=True,
        )


if __name__ == "__main__":
    main()
    
