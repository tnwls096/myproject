# -*- coding: utf-8 -*-
# ============================================================
# 전국 고령화 지도 (시군구별 단계구분도)
#   - 연도 슬라이더로 해마다 비교
#   - 지표 선택: 고령화율(65세 이상) / 유소년 비율(0~14세)
#   - 시도 선택으로 지역 확대
#   - 스트림릿 클라우드 배포용
#   - 필요한 라이브러리: streamlit, pandas, numpy, plotly, requests
# ============================================================

import io          # 내려받은 파일을 메모리에서 바로 읽으려고 사용
import re          # 나이 열 이름에서 숫자(나이)를 뽑아내려고 사용
import requests    # 인터넷에서 데이터 파일을 내려받으려고 사용
import numpy as np
import pandas as pd
import streamlit as st
import plotly.express as px

# ------------------------------------------------------------
# 0. 페이지 기본 설정
# ------------------------------------------------------------
st.set_page_config(page_title="전국 고령화 지도", page_icon="🗺️", layout="wide")

# 데이터가 있는 인터넷 주소 (변하지 않으니 상수로 적어 둠)
POP_URL = "https://raw.githubusercontent.com/greatsong/modudata/main/data/population_yearly.csv.gz"
GEO_URL = "https://raw.githubusercontent.com/greatsong/modudata/main/data/boundaries/sigungu_kr.geojson"

# ------------------------------------------------------------
# 지표별 설정
#   - key   : 계산에 쓸 인구 열 이름
#   - short : 화면에 보여줄 짧은 이름
#   - edges : 색을 5단계로 끊는 경계값 (양끝은 무한대)
#   - labels: 각 구간에 붙일 한글 이름표
#   - colors: 옅은 색 → 진한 색 (낮을수록 옅게, 높을수록 진하게)
#   ※ 연도가 바뀌어도 경계값은 그대로여서 해마다 색을 비교할 수 있음
# ------------------------------------------------------------
METRICS = {
    "고령화율 (65세 이상)": {
        "key": "노인인구",
        "short": "고령화율",
        "edges": [-np.inf, 19, 23, 28, 38, np.inf],
        "labels": ["19% 미만", "19% ~ 23%", "23% ~ 28%", "28% ~ 38%", "38% 이상"],
        "colors": ["#ffffb2", "#fecc5c", "#fd8d3c", "#f03b20", "#bd0026"],  # 노랑→빨강
    },
    "유소년 비율 (0~14세)": {
        "key": "유소년인구",
        "short": "유소년 비율",
        # 유소년은 비율이 훨씬 낮아(대략 3~20%) 고령화율과 다른 경계값을 씀
        "edges": [-np.inf, 8, 10, 12, 15, np.inf],
        "labels": ["8% 미만", "8% ~ 10%", "10% ~ 12%", "12% ~ 15%", "15% 이상"],
        "colors": ["#eff3ff", "#bdd7e7", "#6baed6", "#3182bd", "#08519c"],  # 옅은파랑→진한파랑
    },
}

NODATA_LABEL = "정보 없음"   # 경계와 코드가 안 맞는 지역에 붙일 이름표
NODATA_COLOR = "#d9d9d9"     # 그 지역을 칠할 회색


# ------------------------------------------------------------
# 1. 코드 리매핑
#   연도에 따라 행정구역이 개편돼 옛 코드가 경계 파일과 다를 수 있어
#   경계 파일(현재 기준)에 맞도록 몇 가지를 바꿔 준다.
# ------------------------------------------------------------
def remap_code(code5):
    """옛 시군구 코드(5자리)를 현재 경계 파일 기준으로 바꿔 준다."""
    if code5 == "47720":              # 군위군: 경상북도(47) → 대구광역시(27)
        return "27720"
    if code5.startswith("42"):        # 옛 강원 코드 42 → 강원특별자치도 51
        return "51" + code5[2:]
    if code5.startswith("45"):        # 옛 전북 코드 45 → 전북특별자치도 52
        return "52" + code5[2:]
    return code5


# ------------------------------------------------------------
# 2. 데이터 불러오기 (한 번 받으면 캐시에 저장해 두고 재사용)
# ------------------------------------------------------------
@st.cache_data(show_spinner="인구 데이터를 불러오는 중...")
def load_population():
    """인구 CSV(gzip 압축)를 내려받아 데이터프레임으로 돌려준다."""
    resp = requests.get(POP_URL, timeout=120)
    resp.raise_for_status()
    # '코드'는 숫자가 아니라 이름표이므로 반드시 글자(str)로 읽는다.
    return pd.read_csv(io.BytesIO(resp.content), compression="gzip", dtype={"코드": str})


@st.cache_data(show_spinner="지도 경계를 불러오는 중...")
def load_geojson():
    """시군구 경계 GeoJSON을 내려받아 파이썬 딕셔너리로 돌려준다."""
    resp = requests.get(GEO_URL, timeout=120)
    resp.raise_for_status()
    return resp.json()


# ------------------------------------------------------------
# 3. 인구 집계 (연도 × 시군구 단위로 미리 계산해 둔다)
# ------------------------------------------------------------
def age_of(col_name):
    """'계_65세' 같은 열 이름에서 나이 숫자를 뽑아낸다. '100세 이상'은 100으로."""
    if "100세 이상" in col_name:
        return 100
    m = re.search(r"(\d+)세", col_name)
    return int(m.group(1)) if m else None


@st.cache_data(show_spinner="인구를 집계하는 중...")
def prepare(df):
    """모든 연도에 대해 시군구별 총인구·노인인구·유소년인구를 계산한다."""
    df = df.copy()

    # (1) 남녀 합계 열('계_')만 고르고, 65세 이상 / 0~14세 열을 나눈다
    total_cols = [c for c in df.columns if c.startswith("계_")]        # 0세~100세 이상
    old_cols = [c for c in total_cols if age_of(c) >= 65]              # 65세 이상
    youth_cols = [c for c in total_cols if age_of(c) <= 14]            # 0~14세

    # (2) 인구 숫자를 안전하게 숫자형으로 바꾼다 (빈칸은 0으로)
    df[total_cols] = df[total_cols].apply(pd.to_numeric, errors="coerce").fillna(0)

    # (3) 읍·면·동마다 필요한 인구를 더한다
    df["총인구"] = df[total_cols].sum(axis=1)
    df["노인인구"] = df[old_cols].sum(axis=1)
    df["유소년인구"] = df[youth_cols].sum(axis=1)

    # (4) '코드' 앞 5자리가 시군구 → 리매핑까지 적용
    df["시군구코드"] = df["코드"].str[:5].map(remap_code)

    # (5) 연도·시군구별로 합친다 (이름은 표시에만 사용)
    agg = df.groupby(["연도", "시군구코드"]).agg(
        총인구=("총인구", "sum"),
        노인인구=("노인인구", "sum"),
        유소년인구=("유소년인구", "sum"),
        시도=("시도", "first"),
        시군구=("시군구", "first"),
    ).reset_index()
    return agg


@st.cache_data(show_spinner=False)
def boundary_frame(_geojson):
    """경계 파일에서 (코드·시군구·시도)만 뽑아 표로 만든다."""
    rows = [
        {
            "코드": f["properties"]["코드"],
            "시군구": f["properties"]["시군구"],
            "시도": f["properties"]["시도"],
        }
        for f in _geojson["features"]
    ]
    return pd.DataFrame(rows)


# ============================================================
# 4. 실제 실행 부분
# ============================================================
# --- 데이터 준비 (오류 나면 안내하고 멈춤) ---
try:
    pop_df = load_population()
    geojson = load_geojson()
    agg = prepare(pop_df)
    bframe = boundary_frame(geojson)
except Exception as e:
    st.error(f"데이터를 불러오는 중 문제가 생겼습니다: {e}")
    st.stop()

# ------------------------------------------------------------
# 4-1. 사이드바: 지표 · 연도 · 시도 선택
# ------------------------------------------------------------
st.sidebar.header("⚙️ 지도 설정")
metric_name = st.sidebar.selectbox("① 지표 선택", list(METRICS.keys()))
M = METRICS[metric_name]

years = sorted(agg["연도"].unique())
year = st.sidebar.slider("② 연도", min(years), max(years), max(years), step=1)

sido_options = ["전국"] + sorted(bframe["시도"].unique())
sido_sel = st.sidebar.selectbox("③ 시도 확대", sido_options)

st.sidebar.markdown("---")
st.sidebar.caption("색 구간 경계값은 연도가 바뀌어도 고정돼 해마다 색을 비교할 수 있어요.")

# ------------------------------------------------------------
# 4-2. 제목 (지표에 따라 바뀜)
# ------------------------------------------------------------
if M["short"] == "고령화율":
    st.title("🗺️ 전국 고령화 지도")
else:
    st.title("🗺️ 전국 유소년 인구 지도")
st.caption(f"{year}년 기준 · 시군구별 {M['short']}을(를) 5단계 색으로 나타낸 단계구분도입니다.")

# ------------------------------------------------------------
# 4-3. 선택한 연도의 값 계산
# ------------------------------------------------------------
d = agg[agg["연도"] == year].copy()
d["시군구"] = d["시군구"].fillna(d["시도"])          # 세종처럼 시군구가 비면 시도 이름으로
d = d[d["총인구"] > 0].copy()                        # 인구 0인 곳은 제외
d["값"] = d[M["key"]] / d["총인구"] * 100            # 선택한 지표의 비율(%)

# 전국 값(모든 지역 인구를 합쳐 계산)
nat_ratio = d[M["key"]].sum() / d["총인구"].sum() * 100
top_row = d.loc[d["값"].idxmax()]                    # 가장 높은 시군구
low_row = d.loc[d["값"].idxmin()]                    # 가장 낮은 시군구

# ------------------------------------------------------------
# 4-4. 지표 카드 세 장 (전국 기준)
# ------------------------------------------------------------
card1, card2, card3 = st.columns(3)
with card1:
    st.metric(f"전국 {M['short']}", f"{nat_ratio:.1f}%")
    st.caption("🇰🇷 전국 전체 기준")
with card2:
    st.metric("가장 높은 시군구", f"{top_row['값']:.1f}%")
    st.caption(f"📍 {top_row['시도']} {top_row['시군구']}")
with card3:
    st.metric("가장 낮은 시군구", f"{low_row['값']:.1f}%")
    st.caption(f"📍 {low_row['시도']} {low_row['시군구']}")

# ------------------------------------------------------------
# 4-5. 지도용 데이터 만들기
#   경계 파일의 모든 지역(코드)에 값을 붙이고,
#   값이 없는(코드가 안 맞는) 지역은 '정보 없음'(회색)으로 둔다.
# ------------------------------------------------------------
plot = bframe.merge(d[["시군구코드", "값"]], left_on="코드", right_on="시군구코드", how="left")

# 값을 5단계 구간으로 끊고, 값이 없으면 '정보 없음'으로
plot["구간"] = pd.cut(plot["값"], bins=M["edges"], labels=M["labels"], right=False)
plot["구간"] = plot["구간"].cat.add_categories([NODATA_LABEL]).fillna(NODATA_LABEL)

# 마우스를 올렸을 때 보여줄 값 (없으면 '정보 없음')
plot[M["short"]] = plot["값"].map(lambda v: f"{v:.1f}%" if pd.notna(v) else NODATA_LABEL)

# 시도를 골랐으면 그 시도만 남겨서 확대해 보여 준다
if sido_sel != "전국":
    plot = plot[plot["시도"] == sido_sel]

# ------------------------------------------------------------
# 4-6. 지도 그리기 (배경 타일 없이 경계선만)
# ------------------------------------------------------------
color_map = dict(zip(M["labels"], M["colors"]))
color_map[NODATA_LABEL] = NODATA_COLOR
order = M["labels"] + [NODATA_LABEL]     # 범례 순서: 낮은→높은→정보없음

fig = px.choropleth(
    plot,
    geojson=geojson,
    locations="코드",                     # 우리 표에서 지역을 가리키는 열
    featureidkey="properties.코드",       # 경계 파일에서 지역을 가리키는 값 (이름 아닌 코드로 매칭!)
    color="구간",
    color_discrete_map=color_map,
    category_orders={"구간": order},
    hover_name="시군구",                  # 마우스 올리면 굵게 나오는 이름
    hover_data={                          # 함께 보여줄 정보
        "시도": True,
        M["short"]: True,                 # 예: 고령화율 = 32.1%
        "코드": False,
        "구간": False,
        "값": False,
        "시군구코드": False,
    },
)
fig.update_geos(visible=False, fitbounds="locations")   # 배경 지도 끄고 지역에 화면 맞춤
fig.update_traces(marker_line_width=0.4, marker_line_color="white")
fig.update_layout(
    legend_title_text=f"{M['short']} 구간",
    margin=dict(l=0, r=0, t=0, b=0),
    height=650,
)
st.plotly_chart(fig, use_container_width=True)

# ------------------------------------------------------------
# 4-7. 회색(정보 없음) 지역 안내 문구
# ------------------------------------------------------------
gray = plot[plot["구간"] == NODATA_LABEL]
if len(gray) > 0:
    names = ", ".join(gray["시도"] + " " + gray["시군구"])
    st.info(
        f"ℹ️ {year}년에는 행정구역 개편 등으로 경계 파일과 코드가 맞지 않아 "
        f"회색으로 표시된 지역이 {len(gray)}곳 있습니다: {names}"
    )

# ------------------------------------------------------------
# 4-8. 지도 아래 표 두 개 (높은 곳 10 / 낮은 곳 10, 전국 기준)
# ------------------------------------------------------------
value_col = f"{M['short']}(%)"
show = d[["시도", "시군구", "값"]].copy()
show["값"] = show["값"].round(1)
show = show.rename(columns={"값": value_col})

col_left, col_right = st.columns(2)
with col_left:
    st.markdown(f"### 🔴 {M['short']} 높은 곳 TOP 10")
    top10 = show.sort_values(value_col, ascending=False).head(10).reset_index(drop=True)
    top10.index = top10.index + 1        # 순위를 1부터 표시
    st.dataframe(top10, use_container_width=True)
with col_right:
    st.markdown(f"### 🟢 {M['short']} 낮은 곳 TOP 10")
    bottom10 = show.sort_values(value_col, ascending=True).head(10).reset_index(drop=True)
    bottom10.index = bottom10.index + 1
    st.dataframe(bottom10, use_container_width=True)

st.caption("지표 카드와 표는 모두 전국 기준입니다. · 데이터 출처: greatsong/modudata")
