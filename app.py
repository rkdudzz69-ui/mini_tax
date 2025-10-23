# app.py
import io
import re
import pandas as pd
import streamlit as st

# ==============================
# 기본 설정
# ==============================
st.set_page_config(page_title="사업자 파일 업로드하기", layout="wide")
st.title("사업자 파일 업로드하기")
st.caption("AI 검색: 파일 업로드 후 상호/대표자/사업자번호/주민번호로 폐업 여부를 빠르게 조회하세요.")

# ==============================
# 예시 데이터 (업로드 없을 때 사용)
# ==============================
SAMPLE_DATA = {
    "상호": ["A상사", "B무역", "C식당", "D전자", "E상점", "F기업", "G상회"],
    "사업자번호": ["111-11-11111", "222-22-22222", "333-33-33333", "444-44-44444", "555-55-55555", "666-66-66666", "777-77-77777"],
    "대표자": ["홍길동", "김철수", "이영희", "박민수", "최유진", "정다혜", "오성민"],
    "주민번호": ["800101-1234567", "820202-2345678", "830303-3456789", "840404-4567890", "850505-5678901", "860606-6789012", "870707-7890123"],
    "사업자상태": ["계속사업자", "폐업", "폐업", "계속사업자", "폐업", "계속사업자", "계속사업자"],
    "폐업일자": ["", "2020-03-01", "2021-05-10", "", "2023-01-30", "", ""]
}

# ==============================
# 유틸 함수
# ==============================
@st.cache_data(show_spinner=False)
def load_df_from_file(file) -> pd.DataFrame:
    name = file.name.lower()
    if name.endswith(".csv"):
        content = file.read()
        for enc in ("utf-8-sig", "cp949", "euc-kr", "utf-8"):
            try:
                return pd.read_csv(io.BytesIO(content), encoding=enc)
            except Exception:
                continue
        return pd.read_csv(io.BytesIO(content), encoding_errors="ignore")
    else:
        return pd.read_excel(file)

def normalize_cols(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [str(c).strip() for c in out.columns]
    for c in out.columns:
        if out[c].dtype == "object":
            out[c] = out[c].astype(str).str.strip()
    return out

def digits_only(s: str) -> str:
    return re.sub(r"[^0-9]", "", s or "")

def norm_text(s: str) -> str:
    return (s or "").strip().lower()

# ==============================
# 데이터 로드
# ==============================
file = st.file_uploader("사업내역 파일 업로드 (.xlsx, .xls, .csv)", type=["xlsx", "xls", "csv"])
if file:
    df = load_df_from_file(file)
else:
    st.info("업로드가 없어서 예시 데이터를 사용 중이에요. 실제 파일을 올리면 그걸로 분석해요.")
    df = pd.DataFrame(SAMPLE_DATA)

df = normalize_cols(df)

# 필수 컬럼 체크
required = {"상호", "사업자번호", "대표자", "주민번호", "사업자상태"}
missing = [c for c in required if c not in df.columns]
if missing:
    st.error(f"필수 컬럼이 없어요: {', '.join(missing)}")
    st.stop()

# 날짜 파싱 (있을 때만)
if "폐업일자" in df.columns:
    df["폐업일자"] = df["폐업일자"].replace({"": pd.NA})
    df["폐업일자(파싱)"] = pd.to_datetime(df["폐업일자"], errors="coerce")
else:
    df["폐업일자"] = pd.NA
    df["폐업일자(파싱)"] = pd.NaT

# ==============================
# 메인: AI 검색 (항상 상단 고정)
# ==============================
st.markdown("## 🔎 AI 검색")
st.write("검색할 사업자를 입력해주세요 (상호/대표자/사업자번호/주민번호). 여러 키워드는 공백으로 구분해 AND/OR 검색할 수 있어요.")

q = st.text_input("검색할 사업자를 입력해주세요", placeholder="예) 홍길동 111-11-11111 800101-1234567")
mode = st.radio("매칭 방식", ["부분 포함(AND)", "부분 포함(OR)"], horizontal=True)

search_df = df.copy()
if q.strip():
    terms = [t.strip() for t in q.split() if t.strip()]
    search_df["_bnum_d"] = search_df["사업자번호"].apply(digits_only)
    search_df["_rrn_d"] = search_df["주민번호"].apply(digits_only)

    def match_row(row) -> bool:
        hay_text = " ".join([
            norm_text(row.get("상호", "")),
            norm_text(row.get("대표자", "")),
            norm_text(row.get("사업자번호", "")),
            norm_text(row.get("주민번호", "")),
        ])
        hay_digits = " ".join([row["_bnum_d"], row["_rrn_d"]])

        def contains(term: str) -> bool:
            t_txt = term.lower()
            t_dig = digits_only(term)
            ok_txt = (t_txt in hay_text) if t_txt else False
            ok_dig = (bool(t_dig) and t_dig in hay_digits)
            return ok_txt or ok_dig

        checks = [contains(t) for t in terms]
        return all(checks) if mode.startswith("부분 포함(AND)") else any(checks)

    mask = search_df.apply(match_row, axis=1)
    search_df = search_df.loc[mask].drop(columns=["_bnum_d", "_rrn_d"])
else:
    # 검색어 없으면 전체 보여주지 않고 안내만
    search_df = search_df.iloc[0:0]

# 검색 KPI & 결과
k1, k2 = st.columns(2)
k1.metric("업로드 행 수", len(df))
k2.metric("검색 결과 수", len(search_df))

if q.strip() and search_df.empty:
    st.warning("검색 결과가 없습니다. 철자 또는 하이픈(-) 유무를 확인해보세요.")

view_cols = ["상호", "사업자번호", "대표자", "주민번호", "사업자상태", "폐업일자"]
view_cols = [c for c in view_cols if c in search_df.columns]
st.dataframe(search_df.reindex(columns=view_cols), use_container_width=True)

if not search_df.empty:
    st.download_button(
        "⬇️ 검색 결과 CSV 다운로드",
        data=search_df.reindex(columns=view_cols).to_csv(index=False).encode("utf-8-sig"),
        file_name="AI검색_결과.csv",
        mime="text/csv"
    )

st.divider()

# ==============================
# 카테고리 섹션 (사이드바에서 선택)
# ==============================
st.sidebar.header("카테고리")
category = st.sidebar.radio(
    "보기 선택",
    ["전체 폐업자 조회", "연도별 폐업자 수 통계", "동일 사업자(대표자/주민번호) 내역"],
    index=0
)

# ---------- 1) 전체 폐업자 조회 ----------
if category == "전체 폐업자 조회":
    st.markdown("## 📋 전체 폐업자 조회")

    # 기간 필터
    enable_range = st.checkbox("폐업일자 기간으로 필터", value=False)
    start_date = end_date = None
    closed = df[df["사업자상태"].astype(str).str.strip() == "폐업"].copy()

    if enable_range:
        min_d = pd.to_datetime(closed["폐업일자(파싱)"]).min()
        max_d = pd.to_datetime(closed["폐업일자(파싱)"]).max()
        c1, c2 = st.columns(2)
        start_date = c1.date_input("시작일", value=min_d.date() if pd.notna(min_d) else None)
        end_date = c2.date_input("종료일", value=max_d.date() if pd.notna(max_d) else None)
        if start_date and end_date:
            m = (closed["폐업일자(파싱)"] >= pd.to_datetime(start_date)) & (closed["폐업일자(파싱)"] <= pd.to_datetime(end_date))
            closed = closed[m]

    c1, c2 = st.columns(2)
    c1.metric("폐업자 수", len(closed))
    c2.metric("전체 대비 폐업 비율", f"{(len(closed)/len(df)*100):.1f}%" if len(df) else "0.0%")

    cols = ["상호", "사업자번호", "대표자", "주민번호", "사업자상태", "폐업일자"]
    cols = [c for c in cols if c in closed.columns]
    st.dataframe(closed.reindex(columns=cols), use_container_width=True)

    st.download_button(
        "⬇️ 폐업자 목록 CSV 다운로드",
        data=closed.reindex(columns=cols).to_csv(index=False).encode("utf-8-sig"),
        file_name="전체_폐업자_목록.csv",
        mime="text/csv"
    )

# ---------- 2) 연도별 폐업자 수 통계 ----------
elif category == "연도별 폐업자 수 통계":
    st.markdown("## 📈 연도별 폐업자 수 통계")

    # 연도 추출
    closed = df[df["사업자상태"].astype(str).str.strip() == "폐업"].copy()
    closed["폐업연도"] = pd.to_datetime(closed["폐업일자"], errors="coerce").dt.year

    # 옵션: 특정 연도 범위 선택
    years = sorted([int(y) for y in closed["폐업연도"].dropna().unique()]) if not closed.empty else []
    if years:
        y1, y2 = st.select_slider("연도 범위", options=years, value=(years[0], years[-1]))
        yr_mask = closed["폐업연도"].between(y1, y2)
        closed = closed[yr_mask]
    else:
        st.info("폐업 연도 정보가 없습니다.")

    agg = (
        closed["폐업연도"]
        .dropna()
        .value_counts()
        .sort_index()
        .rename_axis("연도")
        .reset_index(name="폐업자 수")
    )

    st.dataframe(agg, use_container_width=True)
    if not agg.empty:
        st.bar_chart(agg.set_index("연도"))

    st.download_button(
        "⬇️ 연도별 통계 CSV 다운로드",
        data=agg.to_csv(index=False).encode("utf-8-sig"),
        file_name="연도별_폐업자_통계.csv",
        mime="text/csv"
    )

# ---------- 3) 동일 사업자(대표자/주민번호) 내역 ----------
else:
    st.markdown("## 👥 동일 사업자(대표자 또는 주민번호 동일) 내역")

    # 대표자/주민번호 기준 중복 집계
    dup_by_owner = df.groupby("대표자", dropna=False).size().reset_index(name="건수")
    dup_by_owner = dup_by_owner[dup_by_owner["건수"] > 1].sort_values("건수", ascending=False)

    dup_by_rrn = df.groupby("주민번호", dropna=False).size().reset_index(name="건수")
    dup_by_rrn = dup_by_rrn[dup_by_rrn["건수"] > 1].sort_values("건수", ascending=False)

    st.subheader("중복 요약")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**대표자 기준 중복**")
        st.dataframe(dup_by_owner, use_container_width=True, height=260)
    with c2:
        st.markdown("**주민번호 기준 중복**")
        st.dataframe(dup_by_rrn, use_container_width=True, height=260)

    st.download_button(
        "⬇️ 대표자 중복 요약 CSV",
        data=dup_by_owner.to_csv(index=False).encode("utf-8-sig"),
        file_name="대표자_중복_요약.csv",
        mime="text/csv"
    )
    st.download_button(
        "⬇️ 주민번호 중복 요약 CSV",
        data=dup_by_rrn.to_csv(index=False).encode("utf-8-sig"),
        file_name="주민번호_중복_요약.csv",
        mime="text/csv"
    )

    st.subheader("상세 조회")
    mode_key = st.radio("조회 기준", ["대표자", "주민번호"], horizontal=True)
    if mode_key == "대표자":
        candidates = dup_by_owner["대표자"].tolist()
        sel = st.selectbox("대표자 선택", options=candidates if candidates else ["(중복 없음)"])
        if candidates:
            detail = df[df["대표자"] == sel].copy()
        else:
            detail = df.iloc[0:0]
    else:
        candidates = dup_by_rrn["주민번호"].tolist()
        sel = st.selectbox("주민번호 선택", options=candidates if candidates else ["(중복 없음)"])
        if candidates:
            detail = df[df["주민번호"] == sel].copy()
        else:
            detail = df.iloc[0:0]

    cols = ["상호", "사업자번호", "대표자", "주민번호", "사업자상태", "폐업일자"]
    cols = [c for c in cols if c in detail.columns]
    st.dataframe(detail.reindex(columns=cols), use_container_width=True)

    if not detail.empty:
        st.download_button(
            "⬇️ 상세 내역 CSV 다운로드",
            data=detail.reindex(columns=cols).to_csv(index=False).encode("utf-8-sig"),
            file_name=f"동일사업자_상세_{mode_key}.csv",
            mime="text/csv"
        )

# ==============================
# 안내
# ==============================
with st.expander("안내"):
    st.write(
        "- AI 검색: 대소문자 구분 없이 부분 일치로 검색합니다.\n"
        "- 사업자번호/주민번호는 하이픈(-) 유무와 상관없이 숫자 기준으로도 매칭합니다.\n"
        "- ‘동일 사업자 내역’은 대표자 또는 주민번호가 동일한 경우를 찾아 보여줍니다."
    )
