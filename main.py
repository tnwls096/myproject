# -*- coding: utf-8 -*-
# ============================================================
# 전국 고령화 지도 (시군구별 65세 이상 인구 비율 단계구분도)
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

# 색을 나눌 5단계의 구간 경계값(%)과, 각 구간에 붙일 한글 이름표
BREAKS = [19, 23, 28, 38]                          # 구간을 끊는 4개의 경계값
BIN_EDGES = [-np.inf, 19, 23, 28, 38, np.inf]      # pd.cut에 넣을 실제 경계 (양끝은 무한대)
BIN_LABELS = ["19% 미만", "19% ~ 23%", "23% ~ 28%", "28% ~ 38%", "38% 이상"]
# 낮은 쪽은 옅게(연노랑), 높은 쪽은 진하게(진빨강) — 5단계 색
BIN_COLORS = ["#ffffb2", "#fecc5c", "#fd8d3c", "#f03b20", "#bd0026"]
COLOR_MAP = dict(zip(BIN_LABELS, BIN_COLORS))       # {구간이름: 색} 형태로 묶기


# ------------------------------------------------------------
# 1. 데이터 불러오기 (한 번 받으면 캐시에 저장해 두고 재사용)
# ------------------------------------------------------------
@st.cache_data(show_spinner="인구 데이터를 불러오는 중...")
def load_population():
    """인구 CSV(gzip 압축)를 내려받아 데이터프레임으로 돌려준다."""
    resp = requests.get(POP_URL, timeout=120)
    resp.raise_for_status()  # 내려받기에 실패하면 여기서 오류를 내 줌
    # '코드'는 숫자가 아니라 이름표이므로 반드시 글자(str)로 읽는다.
    df = pd.read_csv(io.BytesIO(resp.content), compression="gzip", dtype={"코드": str})
    return df


@st.cache_data(show_spinner="지도 경계를 불러오는 중...")
def load_geojson():
    """시군구 경계 GeoJSON을 내려받아 파이썬 딕셔너리로 돌려준다."""
    resp = requests.get(GEO_URL, timeout=120)
    resp.raise_for_status()
    return resp.json()


# ------------------------------------------------------------
# 2. 고령화율 계산 (시군구 단위로 집계)
# ------------------------------------------------------------
def is_65_plus(col_name):
    """'계_65세'처럼 65세 이상을 뜻하는 열이면 True를 돌려준다."""
    if "100세 이상" in col_name:      # '계_100세 이상'은 무조건 65세 이상
        return True
    m = re.search(r"(\d+)세", col_name)  # 열 이름에서 나이 숫자를 뽑음
    return bool(m) and int(m.group(1)) >= 65


@st.cache_data(show_spinner="고령화율을 계산하는 중...")
def make_aging_table(df):
    """가장 최신 연도를 골라 시군구별 고령화율 표를 만든다."""
    # (1) 가장 최신 연도만 남기기
    latest_year = int(df["연도"].max())
    df = df[df["연도"] == latest_year].copy()

    # (2) 남녀 합계 열('계_')만 고르고, 그중 65세 이상 열을 따로 추린다
    total_cols = [c for c in df.columns if c.startswith("계_")]          # 0세~100세 이상 전체
    old_cols = [c for c in total_cols if is_65_plus(c)]                  # 65세~100세 이상

    # (3) 인구 숫자를 안전하게 숫자형으로 바꾼다 (혹시 모를 빈칸은 0으로)
    df[total_cols] = df[total_cols].apply(pd.to_numeric, errors="coerce").fillna(0)

    # (4) 읍·면·동마다 전체 인구와 노인 인구를 더한다
    df["총인구"] = df[total_cols].sum(axis=1)
    df["노인인구"] = df[old_cols].sum(axis=1)

    # (5) '코드' 앞 5자리가 시군구를 가리키므로, 그것으로 묶는다
    df["시군구코드"] = df["코드"].str[:5]

    grouped = df.groupby("시군구코드").agg(
        총인구=("총인구", "sum"),
        노인인구=("노인인구", "sum"),
        시도=("시도", "first"),      # 이름은 표시에만 쓰고, 지도 매칭은 코드로 함
        시군구=("시군구", "first"),
    ).reset_index()

    # (6) 고령화율(%) = 노인인구 / 총인구 × 100
    grouped["고령화율"] = grouped["노인인구"] / grouped["총인구"] * 100

    # (7) 고령화율을 5개 구간으로 끊어서 이름표를 붙인다 (왼쪽 포함, 오른쪽 미포함)
    grouped["구간"] = pd.cut(
        grouped["고령화율"], bins=BIN_EDGES, labels=BIN_LABELS, right=False
    )

    return grouped, latest_year


# ------------------------------------------------------------
# 3. 실제 실행 부분
# ------------------------------------------------------------
st.title("🗺️ 전국 고령화 지도")
st.caption("시군구별 65세 이상 인구 비율을 5단계 색으로 나타낸 단계구분도입니다.")

# 데이터 불러오고 계산하기 (오류가 나면 안내 문구 표시)
try:
    pop_df = load_population()
    geojson = load_geojson()
    table, year = make_aging_table(pop_df)
except Exception as e:
    st.error(f"데이터를 불러오는 중 문제가 생겼습니다: {e}")
    st.stop()

st.subheader(f"📅 {year}년 기준 (전국 {len(table)}개 시군구)")

# ------------------------------------------------------------
# 4. 지도 그리기 (배경 타일 없이 경계선만)
# ------------------------------------------------------------
fig = px.choropleth(
    table,
    geojson=geojson,
    locations="시군구코드",              # 우리 표에서 지역을 가리키는 열
    featureidkey="properties.코드",      # GeoJSON 안에서 지역을 가리키는 값 (이름 아닌 코드로 매칭!)
    color="구간",                        # 5단계 구간으로 색을 칠함
    color_discrete_map=COLOR_MAP,        # 각 구간에 지정한 색
    category_orders={"구간": BIN_LABELS},  # 범례 순서를 낮은→높은 구간으로 고정
    hover_name="시군구",                 # 마우스를 올리면 굵게 나오는 이름
    hover_data={                         # 함께 보여줄 정보
        "시도": True,
        "고령화율": ":.1f",              # 소수점 한 자리까지
        "시군구코드": False,             # 코드는 숨김
        "구간": False,                   # 구간 이름은 숨김 (색으로 이미 보임)
    },
)

# 배경 지도(위성/도로 타일)를 모두 끄고, 우리 지역들에만 화면을 맞춘다
fig.update_geos(visible=False, fitbounds="locations")
# 경계선을 흰색 가는 선으로 그려 지역 구분이 잘 보이게 함
fig.update_traces(marker_line_width=0.4, marker_line_color="white")
fig.update_layout(
    legend_title_text="고령화율 구간",
    margin=dict(l=0, r=0, t=0, b=0),
    height=650,
)

st.plotly_chart(fig, use_container_width=True)

# ------------------------------------------------------------
# 5. 지도 아래 표 두 개 (높은 곳 10 / 낮은 곳 10)
# ------------------------------------------------------------
# 표에 보여줄 열만 골라 소수점 한 자리로 정리
show = table[["시도", "시군구", "고령화율"]].copy()
show["고령화율"] = show["고령화율"].round(1)
show = show.rename(columns={"고령화율": "고령화율(%)"})

col_left, col_right = st.columns(2)

with col_left:
    st.markdown("### 🔴 고령화율 높은 곳 TOP 10")
    top10 = show.sort_values("고령화율(%)", ascending=False).head(10).reset_index(drop=True)
    top10.index = top10.index + 1  # 순위를 1부터 표시
    st.dataframe(top10, use_container_width=True)

with col_right:
    st.markdown("### 🟢 고령화율 낮은 곳 TOP 10")
    bottom10 = show.sort_values("고령화율(%)", ascending=True).head(10).reset_index(drop=True)
    bottom10.index = bottom10.index + 1
    st.dataframe(bottom10, use_container_width=True)

st.caption("데이터 출처: greatsong/modudata (읍·면·동 인구 및 시군구 경계)")
