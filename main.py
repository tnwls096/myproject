# -*- coding: utf-8 -*-
# ============================================================
# 한눈에 보는 전국 인구 지표 지도 (시군구별 단계구분도)
#   - 지표 4종: 고령화율 / 유소년 비율 / 생산연령인구 비중 / 인구소멸위험지수
#   - 연도 슬라이더로 해마다 비교 (색 구간 경계값은 고정)
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
st.set_page_config(page_title="한눈에 보는 전국 인구 지표 지도", page_icon="🗺️", layout="wide")

# 데이터가 있는 인터넷 주소 (변하지 않으니 상수로 적어 둠)
POP_URL = "https://raw.githubusercontent.com/greatsong/modudata/main/data/population_yearly.csv.gz"
GEO_URL = "https://raw.githubusercontent.com/greatsong/modudata/main/data/boundaries/sigungu_kr.geojson"

NODATA_LABEL = "정보 없음"   # 경계와 코드가 안 맞는 지역에 붙일 이름표
NODATA_COLOR = "#d9d9d9"     # 그 지역을 칠할 회색


# ------------------------------------------------------------
# 지표별 설정
#   각 지표는 아래 정보를 갖는다.
#   - short   : 화면에 보여줄 짧은 이름
#   - value   : 시군구별 값을 구하는 함수 (표 d를 받아 값 Series를 돌려줌)
#   - national: 전국 값을 구하는 함수
#   - fmt     : 값을 글자로 바꾸는 형식 ('{:.1f}%' 또는 '{:.2f}')
#   - edges   : 색을 5단계로 끊는 경계값 (양끝은 무한대, 연도가 바뀌어도 고정)
#   - labels  : 각 구간에 붙일 한글 이름표
#   - colors  : 옅은 색 → 진한 색
#   - hint    : 지표 설명 한 줄
# ------------------------------------------------------------
def pct_value(col):
    """(해당 인구 / 총인구 × 100)을 구하는 함수를 돌려준다."""
    return lambda d: d[col] / d["총인구"] * 100

def pct_national(col):
    """전국 기준 (해당 인구 합 / 총인구 합 × 100)."""
    return lambda d: d[col].sum() / d["총인구"].sum() * 100


METRICS = {
    "고령화율 (65세 이상)": {
        "short": "고령화율",
        "value": pct_value("노인인구"),
        "national": pct_national("노인인구"),
        "fmt": "{:.1f}%",
        "edges": [-np.inf, 19, 23, 28, 38, np.inf],
        "labels": ["19% 미만", "19% ~ 23%", "23% ~ 28%", "28% ~ 38%", "38% 이상"],
        "colors": ["#ffffb2", "#fecc5c", "#fd8d3c", "#f03b20", "#bd0026"],  # 노랑→빨강
        "hint": "65세 이상 인구가 전체에서 차지하는 비율 (높을수록 진한 색)",
    },
    "유소년 비율 (0~14세)": {
        "short": "유소년 비율",
        "value": pct_value("유소년인구"),
        "national": pct_national("유소년인구"),
        "fmt": "{:.1f}%",
        # 유소년은 비율이 낮아(대략 3~20%) 고령화율과 다른 경계값을 씀
        "edges": [-np.inf, 8, 10, 12, 15, np.inf],
        "labels": ["8% 미만", "8% ~ 10%", "10% ~ 12%", "12% ~ 15%", "15% 이상"],
        "colors": ["#eff3ff", "#bdd7e7", "#6baed6", "#3182bd", "#08519c"],  # 옅은파랑→진한파랑
        "hint": "0~14세 인구가 전체에서 차지하는 비율 (높을수록 진한 색)",
    },
    "생산연령인구 비중 (15~64세)": {
        "short": "생산연령인구 비중",
        "value": pct_value("생산연령인구"),
        "national": pct_national("생산연령인구"),
        "fmt": "{:.1f}%",
        # 생산연령 비중은 대략 45~80% 범위
        "edges": [-np.inf, 58, 63, 68, 72, np.inf],
        "labels": ["58% 미만", "58% ~ 63%", "63% ~ 68%", "68% ~ 72%", "72% 이상"],
        "colors": ["#edf8e9", "#bae4b3", "#74c476", "#31a354", "#006d2c"],  # 옅은초록→진한초록
        "hint": "15~64세(일할 수 있는 나이) 인구 비율. 높을수록 경제활동 기반이 탄탄 (진한 색)",
    },
    "인구소멸위험지수": {
        "short": "소멸위험지수",
        # 소멸위험지수 = 20~39세 여성 ÷ 65세 이상 (노인 인구가 0이면 계산 불가 → 제외)
        "value": lambda d: d["가임여성인구"] / d["노인인구"].replace(0, np.nan),
        "national": lambda d: d["가임여성인구"].sum() / d["노인인구"].sum(),
        "fmt": "{:.2f}",
        # 이상호(한국고용정보원) 지수의 공식 분류 기준
        "edges": [-np.inf, 0.2, 0.5, 1.0, 1.5, np.inf],
        "labels": ["0.2 미만 (소멸 고위험)", "0.2 ~ 0.5 (소멸위험 진입)",
                   "0.5 ~ 1.0 (주의)", "1.0 ~ 1.5 (보통)", "1.5 이상 (양호)"],
        # 낮을수록 위험 → 빨강, 높을수록 안전 → 초록
        "colors": ["#a50026", "#f46d43", "#fee08b", "#a6d96a", "#1a9850"],
        "hint": "20~39세 여성 ÷ 65세 이상. 낮을수록(빨강) 소멸 위험이 큼 (이상호 지수)",
    },
}


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
    """모든 연도에 대해 시군구별로 필요한 인구들을 계산한다."""
    df = df.copy()

    # (1) 계산에 쓸 나이 열들을 종류별로 골라 둔다
    total_cols = [c for c in df.columns if c.startswith("계_")]              # 남녀 합계(0~100+)
    fem_cols   = [c for c in df.columns if c.startswith("여_")]              # 여성(0~100+)
    old_cols   = [c for c in total_cols if age_of(c) >= 65]                  # 65세 이상
    youth_cols = [c for c in total_cols if age_of(c) <= 14]                  # 0~14세
    work_cols  = [c for c in total_cols if 15 <= age_of(c) <= 64]            # 15~64세(생산연령)
    fem2039    = [c for c in fem_cols if 20 <= age_of(c) <= 39]              # 20~39세 여성(가임)

    # (2) 인구 숫자를 안전하게 숫자형으로 바꾼다 (빈칸은 0으로)
    num_cols = total_cols + fem2039
    df[num_cols] = df[num_cols].apply(pd.to_numeric, errors="coerce").fillna(0)

    # (3) 읍·면·동마다 필요한 인구를 더해 새 표를 만든다 (concat으로 한 번에 → 빠름)
    derived = pd.DataFrame({
        "연도": df["연도"],
        "시도": df["시도"],
        "시군구": df["시군구"],
        "시군구코드": df["코드"].str[:5].map(remap_code),   # 앞 5자리 + 리매핑
        "총인구": df[total_cols].sum(axis=1),
        "노인인구": df[old_cols].sum(axis=1),
        "유소년인구": df[youth_cols].sum(axis=1),
        "생산연령인구": df[work_cols].sum(axis=1),
        "가임여성인구": df[fem2039].sum(axis=1),
    })

    # (4) 연도·시군구별로 합친다 (이름은 표시에만 사용)
    agg = derived.groupby(["연도", "시군구코드"]).agg(
        총인구=("총인구", "sum"),
        노인인구=("노인인구", "sum"),
        유소년인구=("유소년인구", "sum"),
        생산연령인구=("생산연령인구", "sum"),
        가임여성인구=("가임여성인구", "sum"),
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
# 4-2. 제목 (항상 같은 제목, 선택한 지표는 아래 설명에)
# ------------------------------------------------------------
st.title("🗺️ 한눈에 보는 전국 인구 지표 지도")
st.caption(f"**{metric_name}** · {year}년 기준 · {M['hint']}")

# ------------------------------------------------------------
# 4-3. 선택한 연도·지표의 값 계산
# ------------------------------------------------------------
d = agg[agg["연도"] == year].copy()
d["시군구"] = d["시군구"].fillna(d["시도"])          # 세종처럼 시군구가 비면 시도 이름으로
d = d[d["총인구"] > 0].copy()                        # 인구 0인 곳은 제외
d["값"] = M["value"](d)                              # 선택한 지표 값

fmt = M["fmt"]                                        # 값을 글자로 바꿀 형식
dd = d.dropna(subset=["값"])                          # 값이 있는 지역만 (카드·표용)

# 전국 값
nat_val = M["national"](d)
top_row = dd.loc[dd["값"].idxmax()]                  # 가장 높은 시군구
low_row = dd.loc[dd["값"].idxmin()]                  # 가장 낮은 시군구

# ------------------------------------------------------------
# 4-4. 지표 카드 세 장 (전국 기준)
# ------------------------------------------------------------
card1, card2, card3 = st.columns(3)
with card1:
    st.metric(f"전국 {M['short']}", fmt.format(nat_val))
    st.caption("🇰🇷 전국 전체 기준")
with card2:
    st.metric("가장 높은 시군구", fmt.format(top_row["값"]))
    st.caption(f"📍 {top_row['시도']} {top_row['시군구']}")
with card3:
    st.metric("가장 낮은 시군구", fmt.format(low_row["값"]))
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
plot[M["short"]] = plot["값"].map(lambda v: fmt.format(v) if pd.notna(v) else NODATA_LABEL)

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
def make_table(ascending):
    """값 기준으로 정렬해 상위 10개를 글자 형식으로 예쁘게 만든다."""
    t = dd.sort_values("값", ascending=ascending).head(10)[["시도", "시군구", "값"]].copy()
    t["값"] = t["값"].map(fmt.format)                 # 숫자로 정렬한 뒤 글자로 변환
    t = t.rename(columns={"값": M["short"]}).reset_index(drop=True)
    t.index = t.index + 1                             # 순위를 1부터 표시
    return t

col_left, col_right = st.columns(2)
with col_left:
    st.markdown(f"### 🔴 {M['short']} 높은 곳 TOP 10")
    st.dataframe(make_table(ascending=False), use_container_width=True)
with col_right:
    st.markdown(f"### 🟢 {M['short']} 낮은 곳 TOP 10")
    st.dataframe(make_table(ascending=True), use_container_width=True)

st.caption("지표 카드와 표는 모두 전국 기준입니다. · 데이터 출처: greatsong/modudata")
