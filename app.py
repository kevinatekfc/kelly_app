import streamlit as st
import pandas as pd
import re
from rapidfuzz import process, fuzz
from io import BytesIO

# CONFIG
FUZZY_DEFAULT = 80
SP500_WIKI    = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"

st.set_page_config(page_title="Kelly‐Fraction Calculator", layout="wide")
st.title("📈 Kelly‐Fraction Calculator")
st.markdown(
    "Upload your realized gains/losses CSV, choose a fuzzy-match threshold, "
    "and download per-ticker Kelly fractions."
)

# Sidebar controls
fuzzy_score = st.sidebar.slider("Fuzzy-match threshold", 20, 100, 40)
show_sample = st.sidebar.checkbox("Show sample normalization", False)

# File uploader
upload = st.file_uploader("Upload your CSV", type=["csv"])
if upload:
    df = pd.read_csv(upload, encoding="ISO-8859-1", low_memory=False)
    st.write("Here’s a preview of your data:", df.head())

# Compute button
if st.button("Compute Kelly Fractions") and upload:
    with st.spinner("Computing…"):
        # 1) Load & clean
        df = df.copy()
        df.columns = df.columns.str.strip()
        gl_cols = [c for c in df.columns if "gain" in c.lower() and "loss" in c.lower()]
        if not gl_cols:
            st.error("No Gain/Loss column found."); st.stop()
        df = df.rename(columns={gl_cols[0]: "Gain_Loss"})
        df["Gain_Loss"] = pd.to_numeric(
            df["Gain_Loss"].astype(str).replace(r"[,\$]", "", regex=True),
            errors="coerce"
        )
        df = df.dropna(subset=["Gain_Loss", "Description"])

        # 2) Normalize
        def normalize(txt):
            t = txt.upper()
            t = re.sub(r'\b(INC|CORP|COMPANY|CO|LTD|LLC|PLC)\.?\b','', t)
            t = re.sub(r'[^A-Z0-9 ]','', t)
            return re.sub(r'\s+', ' ', t).strip()
        df["NormDesc"] = df["Description"].apply(normalize)
        unique_descs = df["NormDesc"].drop_duplicates().tolist()
        if show_sample:
            st.write(df[["Description","NormDesc"]].drop_duplicates().head(5))

        # 3) Fetch S&P 500
        sp500 = pd.read_html(SP500_WIKI)[0]
        sp500 = sp500.rename(columns={"Security":"Name","Symbol":"Ticker"})
        sp500["NormName"] = sp500["Name"].apply(normalize)

        # 4) Fuzzy-match
        mapping = []
        for d in unique_descs:
            match, score, idx = process.extractOne(
                d, sp500["NormName"], scorer=fuzz.token_set_ratio
            )
            if score >= fuzzy_score:
                mapping.append({"NormDesc": d, "Ticker": sp500.at[idx, "Ticker"]})
        map_df = pd.DataFrame(mapping)

        # 5) Merge & Kelly calc
        df2 = df.merge(map_df, on="NormDesc", how="inner")
        df2["Win"] = df2["Gain_Loss"] > 0
        summary = (
            df2.groupby("Ticker")
               .agg(
                   total_trades=("Gain_Loss","count"),
                   wins        =("Win","sum"),
                   avg_win     =("Gain_Loss", lambda x: x[x>0].mean() if (x>0).any() else 0),
                   avg_loss    =("Gain_Loss", lambda x: abs(x[x<0].mean()) if (x<0).any() else 0)
               )
               .reset_index()
        )
        summary["losses"]         = summary["total_trades"] - summary["wins"]
        summary["winrate"]        = summary["wins"] / summary["total_trades"]
        summary["kelly_fraction"] = summary.apply(
            lambda r: max(
                r["winrate"] - (1 - r["winrate"]) * (r["avg_loss"]/r["avg_win"]), 0
            ) if r["avg_win"]>0 else 0,
            axis=1
        )

        # --- NEW: compute average Kelly excluding 0 and 1 ---
        valid = summary["kelly_fraction"].between(0,1, inclusive="neither")
        avg_kelly = summary.loc[valid, "kelly_fraction"].mean() if valid.any() else 0.0

    # Show results
    st.success(f"Mapped {len(map_df)} / {len(unique_descs)} descriptions → {len(summary)} tickers")
    st.markdown(f"**Average Kelly (excl. 0 & 1):** {avg_kelly:.4f}")
    st.dataframe(summary.head(10), use_container_width=True)

    # Download button (full results)
    buf = BytesIO()
    summary.to_excel(buf, index=False)
    buf.seek(0)
    st.download_button(
        "📥 Download Excel",
        data=buf,
        file_name="kelly_output.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

else:
    st.info("Upload a CSV and click the button to compute.")