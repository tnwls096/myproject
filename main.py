import re
import requests
import pandas as pd
import streamlit as st
import plotly.express as px

st.set_page_config(page_title="전국 인구 지표 지도", layout="wide")
st.title("🗺️ 전국 주민등록 인구 지표 지도")
st.caption("행정안전부 주민등록 인구 데이터를 기반으로 시군구별 주요 인구 지표를 시각화합니다.")

POP_URL = "https://raw.githubusercontent.com/greatsong/modudata/main/data/population_yearly.csv.gz"
GEO_URL = "https://raw.githubusercontent.com/greatsong/modudata/main/data/boundaries/sigungu_kr.geojson"


@st.cache_data(show_spinner="인구 데이터를 불러오는 중입니다...")
def load_population():
    return pd.read_csv(POP_URL, dtype={"코드": str})


@st.cache_data(show_spinner="지도 경계를 불러오는 중입니다...")
def load_geojson():
    res = requests.get(GEO_URL, timeout=30).json()
    for feature in res["features"]:
        feature["properties"]["코드"] = str(feature["properties"]["코드"])
    return res


df = load_population()
geojson = load_geojson()

latest_year = int(df["연도"].max())
df = df[df["연도"] == latest_year].copy()

# ---------------------------------------------------------
# 연령별 컬럼 분류 (전체, 유소년, 생산연령, 고령, 20-39세 여성)
# ---------------------------------------------------------
def age_of(col):
    m = re.match(r"(?:계|남|여)_(\d+)세", col)
    return int(m.group(1)) if m else None

total_cols = [c for c in df.columns if c.startswith("계_")]
youth_cols = [c for c in total_cols if age_of(c) is not None and age_of(c) < 15]           # 0~14세
working_cols = [c for c in total_cols if age_of(c) is not None and 15 <= age_of(c) <= 64] # 15~64세
elderly_cols = [c for c in total_cols if age_of(c) is not None and age_of(c) >= 65]        # 65세 이상

# 20~39세 여성 컬럼 (인구소멸위험지수 분모용)
female_2039_cols = [c for c in df.columns if c.startswith("여_") and age_of(c) is not None and 20 <= age_of(c) <= 39]

# 시군구별 합계 집계
df["전체인구"] = df[total_cols].sum(axis=1)
df["유소년인구"] = df[youth_cols].sum(axis=1)
df["생산인구"] = df[working_cols].sum(axis=1)
df["고령인구"] = df[elderly_cols].sum(axis=1)
df["여성2039"] = df[female_2039_cols].sum(axis=1)

df["시군구코드"] = df["코드"].str[:5]
grouped = df.groupby("시군구코드")[["전체인구", "유소년인구", "생산인구", "고령인구", "여성2039"]].sum().reset_index()

# 핵심 지표 계산
grouped["고령화율"] = (grouped["고령인구"] / grouped["전체인구"] * 100).round(2)
grouped["유소년비율"] = (grouped["유소년인구"] / grouped["전체인구"] * 100).round(2)
grouped["생산인구비율"] = (grouped["생산인구"] / grouped["전체인구"] * 100).round(2)
grouped["소멸위험지수"] = (grouped["여성2039"] / grouped["고령인구"]).round(3)

# GeoJSON과 시군구 이름 매칭
names = pd.DataFrame([
    {
        "시군구코드": str(f["properties"]["코드"]),
        "시군구": f["properties"]["시군구"],
        "시도": f["properties"]["시도"],
    }
    for f in geojson["features"]
])
merged = grouped.merge(names, on="시군구코드", how="left")

# ---------------------------------------------------------
# 사이드바 지표 선택 및 범주화 설정
# ---------------------------------------------------------
st.sidebar.header("⚙️ 지표 설정")
selected_metric = st.sidebar.selectbox(
    "분석할 지표를 선택하세요",
    [
        "👵 고령화율 (65세 이상)",
        "👶 유소년 인구 비율 (0~14세)",
        "⚠️ 인구소멸위험지수",
        "💼 생산연령인구 비중 (15~64세)",
    ]
)

if selected_metric == "👵 고령화율 (65세 이상)":
    val_col = "고령화율"
    unit = "%"
    bins = [0, 19, 23, 28, 38, 101]
    labels = ["19% 미만", "19~23%", "23~28%", "28~38%", "38% 이상"]
    colors = {"19% 미만": "#fee6ce", "19~23%": "#fdc086", "23~28%": "#f79646", "28~38%": "#e8590c", "38% 이상": "#a63603"}
    ascending_high_risk = True # 고령화율은 높은 것이 위험/이슈

elif selected_metric == "👶 유소년 인구 비율 (0~14세)":
    val_col = "유소년비율"
    unit = "%"
    bins = [0, 8, 10, 12, 14, 101]
    labels = ["8% 미만", "8~10%", "10~12%", "12~14%", "14% 이상"]
    # 낮을수록 저출생/위험 (붉은색/어두운색), 높을수록 활발 (밝은 푸른색)
    colors = {"8% 미만": "#d73027", "8~10%": "#f46d43", "10~12%": "#fdae61", "12~14%": "#abd9e9", "14% 이상": "#4575b4"}
    ascending_high_risk = False

elif selected_metric == "⚠️ 인구소멸위험지수":
    val_col = "소멸위험지수"
    unit = ""
    # 한국고용정보원 표준 기준: 0.2미만(고위험), 0.2~0.5(진입), 0.5~1.0(주의), 1.0~1.5(보통), 1.5이상(저위험)
    bins = [0, 0.2, 0.5, 1.0, 1.5, 999]
    labels = ["0.2 미만 (소멸고위험)", "0.2~0.5 (소멸위험)", "0.5~1.0 (주의)", "1.0~1.5 (보통)", "1.5 이상 (저위험)"]
    colors = {
        "0.2 미만 (소멸고위험)": "#a50026",
        "0.2~0.5 (소멸위험)": "#f46d43",
        "0.5~1.0 (주의)": "#fee090",
        "1.0~1.5 (보통)": "#e0f3f8",
        "1.5 이상 (저위험)": "#313695"
    }
    ascending_high_risk = False

elif selected_metric == "💼 생산연령인구 비중 (15~64세)":
    val_col = "생산인구비율"
    unit = "%"
    bins = [0, 60, 65, 70, 75, 101]
    labels = ["60% 미만", "60~65%", "65~70%", "70~75%", "75% 이상"]
    colors = {"60% 미만": "#edf8fb", "60~65%": "#b2e2e2", "65~70%": "#66c2a4", "70~75%": "#2ca25f", "75% 이상": "#006d2c"}
    ascending_high_risk = False

# 선택된 지표 기반으로 범주 단계 생성
merged["단계"] = pd.cut(merged[val_col], bins=bins, labels=labels, right=False)

# ---------------------------------------------------------
# 지도 생성 (Choropleth Map)
# ---------------------------------------------------------
fig = px.choropleth(
    merged,
    geojson=geojson,
    locations="시군구코드",
    featureidkey="properties.코드",
    color="단계",
    category_orders={"단계": labels},
    color_discrete_map=colors,
    hover_name="시군구",
    hover_data={val_col: True, "시도": True, "시군구코드": False, "단계": False},
    labels={val_col: f"{selected_metric} ({unit})"},
)
fig.update_geos(fitbounds="locations", visible=False)
fig.update_layout(
    margin=dict(l=0, r=0, t=10, b=0),
    height=680,
    legend_title_text=f"{selected_metric} ({latest_year}년)",
)

st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------
# 상위/하위 10개 시군구 표
# ---------------------------------------------------------
c1, c2 = st.columns(2)
cols = ["시도", "시군구", val_col]

with c1:
    st.subheader(f"🔝 {selected_metric} 높은 지역 TOP 10")
    top10 = merged.nlargest(10, val_col)[cols].reset_index(drop=True)
    st.dataframe(top10, use_container_width=True)

with c2:
    st.subheader(f"🔻 {selected_metric} 낮은 지역 TOP 10")
    bottom10 = merged.nsmallest(10, val_col)[cols].reset_index(drop=True)
    st.dataframe(bottom10, use_container_width=True)
