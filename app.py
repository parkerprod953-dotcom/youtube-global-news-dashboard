# app.py  – Global News & Politics Trending Dashboard

import os
import re
import requests
from datetime import datetime, timezone
from typing import List

import pandas as pd
import streamlit as st

# ------------- CONFIG ---------------------------------------------------------

st.set_page_config(
    page_title="Global News & Politics – Trending Dashboard",
    page_icon="🌍",
    layout="wide",
)

# NOTE: to force dark mode in Streamlit, also create .streamlit/config.toml:
# [theme]
# base="dark"

# ------------- SECRETS / API KEY ---------------------------------------------

API_KEY = st.secrets.get("YOUTUBE_API_KEY") or os.getenv("YOUTUBE_API_KEY")
if not API_KEY:
    st.error(
        "No YouTube API key found. Please set `YOUTUBE_API_KEY` in Streamlit **Secrets** "
        "or as an environment variable."
    )
    st.stop()

YOUTUBE_API_URL = "https://www.googleapis.com/youtube/v3"

# ------------- UTILITIES -----------------------------------------------------

ISO_DURATION_RE = re.compile(
    r"PT"                  # starts with PT
    r"(?:(\d+)H)?"         # hours
    r"(?:(\d+)M)?"         # minutes
    r"(?:(\d+)S)?"         # seconds
)


def parse_iso_duration(s: str) -> int:
    """Return duration in seconds from ISO-8601 string like 'PT3M12S'."""
    if not s:
        return 0
    m = ISO_DURATION_RE.fullmatch(s)
    if not m:
        return 0
    h, m_, s_ = m.groups()
    h = int(h) if h else 0
    m_ = int(m_) if m_ else 0
    s_ = int(s_) if s_ else 0
    return h * 3600 + m_ * 60 + s_


def format_views(n: int) -> str:
    if n >= 1_000_000_000:
        return f"{n/1_000_000_000:.1f}B"
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)


def format_duration_sec(sec: int) -> str:
    if not sec:
        return "–"
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    if h:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:d}:{s:02d}"


def time_ago(published_at: str) -> str:
    try:
        dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        delta = now - dt
        days = delta.days
        seconds = delta.seconds
        if days > 365:
            return f"{days // 365} years ago"
        if days > 30:
            return f"{days // 30} months ago"
        if days > 7:
            return f"{days // 7} weeks ago"
        if days > 0:
            return f"{days} days ago"
        hours = seconds // 3600
        if hours > 0:
            return f"{hours} hours ago"
        minutes = seconds // 60
        if minutes > 0:
            return f"{minutes} minutes ago"
        return "Just now"
    except Exception:
        return ""


# ------------- YOUTUBE API CALL ---------------------------------------------

def fetch_trending_news_for_region(
    region_code: str, max_results: int = 50
) -> pd.DataFrame:
    """
    Fetch trending *News & Politics* videos for a region and return a DataFrame.

    Uses:
    - chart=mostPopular
    - videoCategoryId=25 (News & Politics)
    """
    params = {
        "part": "snippet,statistics,contentDetails",
        "chart": "mostPopular",
        "regionCode": region_code,
        "videoCategoryId": "25",
        "maxResults": max_results,
        "key": API_KEY,
    }

    resp = requests.get(f"{YOUTUBE_API_URL}/videos", params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    videos: List[dict] = []

    for item in data.get("items", []):
        vid = item.get("id")
        snippet = item.get("snippet", {}) or {}
        stats = item.get("statistics", {}) or {}
        details = item.get("contentDetails", {}) or {}
        thumbs = (snippet.get("thumbnails") or {}) or {}

        # Pick a decent thumbnail
        thumb_obj = (
            thumbs.get("medium")
            or thumbs.get("high")
            or thumbs.get("standard")
            or thumbs.get("default")
            or {}
        )
        thumb_url = thumb_obj.get("url")

        # Duration + Shorts detection
        duration_sec = parse_iso_duration(details.get("duration", ""))
        text = (snippet.get("title", "") + " " + snippet.get("description", "")).lower()
        marked_as_shorts = "#shorts" in text or " #short " in text
        is_short = marked_as_shorts or duration_sec <= 75

        videos.append(
            {
                "video_id": vid,
                "title": snippet.get("title", ""),
                "description": snippet.get("description", "") or "",
                "channel_title": snippet.get("channelTitle", "") or "",
                "published_at": snippet.get("publishedAt", ""),
                "view_count": int(stats.get("viewCount", 0)),
                "like_count": int(stats.get("likeCount", 0)) if "likeCount" in stats else None,
                "duration_sec": duration_sec,
                "is_short": is_short,
                "thumbnail_url": thumb_url,
                "url": f"https://www.youtube.com/watch?v={vid}",
            }
        )

    if not videos:
        return pd.DataFrame()

    df = pd.DataFrame(videos)
    df.sort_values("view_count", ascending=False, inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df


# ------------- RENDERING -----------------------------------------------------

CARD_CSS = """
<style>
/* Remove default top white margin */
.block-container {
    padding-top: 1.5rem;
}

/* General dark card style */
.video-card {
    border-radius: 16px;
    background: #141923;
    padding: 14px 18px;
    margin-bottom: 12px;
    display: flex;
    gap: 12px;
    transition: background 0.15s ease, transform 0.15s ease, box-shadow 0.15s ease;
}
.video-card:hover {
    background: #1c2330;
    transform: translateY(-1px);
    box-shadow: 0 10px 20px rgba(0,0,0,0.35);
}

/* Thumbnail */
.video-thumb {
    flex: 0 0 210px;
}
.video-thumb img {
    width: 100%;
    border-radius: 10px;
    object-fit: cover;
}

/* Content */
.video-main {
    flex: 1;
    display: flex;
    flex-direction: column;
}

/* Title & badges */
.video-title {
    font-size: 1.05rem;
    font-weight: 700;
    margin-bottom: 2px;
}
.video-meta {
    font-size: 0.83rem;
    color: #D0D4E0;
    margin-bottom: 4px;
}
.video-channel {
    font-size: 0.85rem;
    color: #B4BAD4;
    margin-bottom: 6px;
}
.video-desc {
    font-size: 0.85rem;
    color: #E1E3ED;
}

/* Tab bubbles tweak (optional, relies on default st.tabs) */
.css-10trblm, .stTabs [data-baseweb="tab"] {
    font-weight: 600;
}
</style>
"""

st.markdown(CARD_CSS, unsafe_allow_html=True)


def render_video_list(df: pd.DataFrame, section_key: str) -> None:
    if df.empty:
        st.info("No videos found for this section.")
        return

    for idx, row in df.iterrows():
        url = row["url"]
        thumb = row["thumbnail_url"]
        title = row["title"]
        ch = row["channel_title"]
        views_str = format_views(int(row["view_count"]))
        dur_str = format_duration_sec(int(row["duration_sec"]))
        age_str = time_ago(row["published_at"])

        desc = row.get("description", "") or ""
        # Truncate description to ~200 characters
        max_chars = 200
        if len(desc) > max_chars:
            short_desc = desc[:max_chars].rsplit(" ", 1)[0] + "…"
        else:
            short_desc = desc

        rank = idx + 1

        card_html = f"""
        <div class="video-card">
            <div class="video-thumb">
                <a href="{url}" target="_blank" rel="noopener noreferrer">
                    <img src="{thumb}" alt="thumbnail"/>
                </a>
            </div>
            <div class="video-main">
                <div class="video-title">
                    #{rank} · <a href="{url}" target="_blank" rel="noopener noreferrer" style="color:#ffffff;text-decoration:none;">
                        {title}
                    </a>
                </div>
                <div class="video-meta">
                    👁 {views_str} views · ⏱ {dur_str} · {age_str}
                </div>
                <div class="video-channel">
                    {ch}
                </div>
                <div class="video-desc">
                    {short_desc}
                </div>
            </div>
        </div>
        """
        st.markdown(card_html, unsafe_allow_html=True)


# ------------- MAIN APP ------------------------------------------------------

REGION_CHOICES = {
    "United States": "US",
    "Canada": "CA",
    "United Kingdom": "GB",
    "India": "IN",
    "Australia": "AU",
    "Germany": "DE",
    "France": "FR",
    "Brazil": "BR",
    "Japan": "JP",
    "Mexico": "MX",
    "Worldwide proxy (use US)": "US",
}


def main():
    st.title("🌍 Global News & Politics – Trending Dashboard")

    st.caption(
        "This dashboard shows **YouTube News & Politics videos** currently trending in "
        "the selected region’s trending list. View counts are global, not region-only."
    )

    col1, col2 = st.columns([2, 1])
    with col1:
        region_label = st.selectbox(
            "Region",
            list(REGION_CHOICES.keys()),
            index=0,
        )
    with col2:
        max_results = st.slider(
            "Max results from API",
            min_value=10,
            max_value=50,
            value=40,
            step=5,
        )

    region_code = REGION_CHOICES[region_label]

    refresh = st.button("🔄 Refresh data now")

    # Fetch data (no cache for simplicity; you could add @st.cache_data)
    df = fetch_trending_news_for_region(
        region_code=region_code, max_results=max_results
    )

    if df.empty:
        st.warning("No videos returned from the API for this region.")
        return

    if "is_short" not in df.columns:
        df["is_short"] = False

    regular_df = df[~df["is_short"]].copy()
    shorts_df = df[df["is_short"]].copy()

    st.markdown(
        f"**Fetched {len(df)} News & Politics videos** for region "
        f"`{region_code}` ({region_label})."
    )

    tabs = st.tabs(["Regular videos", "Shorts", "Raw table"])

    with tabs[0]:
        st.subheader("Top trending regular News & Politics videos")
        st.caption(
            "These are trending News & Politics videos that look like regular 16:9, non-Shorts. "
            "Ranked by current global view count."
        )
        render_video_list(regular_df.head(20), section_key="regular")

    with tabs[1]:
        st.subheader("Top trending News & Politics Shorts")
        st.caption(
            "These are likely **Shorts** (≤ 75 seconds or tagged `#shorts`) in the News & Politics category."
        )
        render_video_list(shorts_df.head(20), section_key="shorts")

    with tabs[2]:
        st.subheader("Raw data")
        st.caption("Full DataFrame of all fetched videos.")
        st.dataframe(df)


if __name__ == "__main__":
    main()
