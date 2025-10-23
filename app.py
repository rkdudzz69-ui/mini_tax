# app.py
import io
import re
import pandas as pd
import streamlit as st

# ======================================
# 기본 설정 (요청사항 반영)
# ======================================
st.set_page_config(page_title="사업자 파일 업로드하기", layout="wide")
st.title("사업자 파일 업로드하기")
st.caption("검색할 사업자를 입력해주세요 · 대표자/상호/사업자번호/주민번호로 부분 검색 · 카테고리 기준 집계/필터")

# ======================================
# 예시 데이터 (업로드 없을 때 사용)
# ======================================
SAMPLE_DATA = {
    "상호": ["A상사", "B무역", "C식당", "D전자", "E상점", "F기업", "G상회"],
    "사업자번호": ["111-11-11111", "222-22-22222", "333-33-33333", "444-44-44444", "555-55-55555", "666-66-66666", "777-77-77777"],
    "대표자": ["홍길동", "김철수", "이영희", "박민수", "최유진", "정다혜", "오성민"],
    "주민번호": ["800101-1234567", "820202-2345678", "830303-3456789", "840404-4567890", "850505-5678901", "860606-6789012", "870707-7890123"],
    "사업자상태": ["계속사업자", "폐업", "폐업", "계속사업자", "폐업", "계속사업자", "계속사업자"],
    "폐업일자": ["", "2020-03-01", "2021-05-10", "", "2023-01-30", "", ""],
    # 예시: 파일에 이미 카테고리가 있으면 자동 후보로 잡힘
    # "카테고리": ["도소매","무역","외식","전자","소매","도소매","도소매"]
}

# ======================================
# 유틸
# ======================================
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
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    for c in df.columns:
        if df[c].dtype == "object":
            df[c] = df[c].astype(str).str.strip()
    return df

def digits_only(s: str) -> str:
    return re.sub(r"[^0-9]", "", s or "")

def norm_text(s: str) -> str:
    return (s or "").strip().lower()

# ======================================
# 데이터 로드
# ======================================
file = st.file_uploader("사업내역 파일 업로드 (.xlsx, .xls, .csv)", type=["xlsx", "xls", "csv"])
if file:
    df = load_df_from_file(file)
else:
    st.info("업로드가 없어서 예시 데이터를 사용 중이에요. 실제 파일을 올리면 그걸로 분석해요.")
    df = pd.DataFrame(SAMPLE_DATA)

df = normalize_cols(df)

# 필수 컬럼 체크
required = {"상호", "사업자번호", "대표자", "주민번호"}
missing = [c for c in required if c not in df.columns]
if missing:
    st.error(f"필수 컬럼이 없어요: {', '.join(missing)}")
    st.stop()

# 날짜 컬럼 정리 (있을 때만)
if "폐업일자" in df.columns:
    df["폐업일자"] = df["폐업일자"].replace({"": pd.NA})
    df["폐업일자(파싱)"] = pd.to_datetime(df["폐업일자"], errors="coerce")

# ======================================
# 사이드바 — 카테고리 형식 (핵심)
# ======================================
st.sidebar.header("카테고리 설정")

cat_mode = st.sidebar.radio(
    "카테고리 만드는 방법",
    ["기존 컬럼 사용", "키워드 규칙"],
    index=0
)

def ensure_category():
    if "카테고리" not in df.columns:
        df["카테고리"] = "미분류"

if cat_mode == "기존 컬럼 사용":
    # 카테고리 후보 자동 제안
    candidates = [c for c in df.columns if any(k in c for k in ["카테고리", "업종", "업태", "지역", "분류"])]
    if candidates:
        cat_col = st.sidebar.selectbox("카테고리로 쓸 컬럼", options=candidates, index=0)
        df["카테고리"] = df[cat_col].astype(str).str.strip().replace({"": "미분류"})
    else:
        st.sidebar.info("추천 컬럼이 없어 임시 ‘카테고리=미분류’를 사용합니다.")
        ensure_category()

else:
    # 키워드 규칙 방식 (기본 대상: 상호)
    rule_text = st.sidebar.text_area(
        "규칙 입력 (한 줄에 ‘카테고리=키워드1|키워드2’)\n예) 전자상거래=전자|온라인\n외식=식당|요리\n도소매=상사|상회",
        value="전자상거래=전자|온라인\n외식=식당|요리\n도소매=상사|상회",
        height=120
    )
    target_col = st.sidebar.selectbox(
        "규칙 적용 대상 컬럼",
        options=[c for c in df.columns],
        index=([c for c in df.columns].index("상호") if "상호" in df.columns else 0)
    )
    df["카테고리"] = "미분류"
    if rule_text.strip():
        for line in rule_text.splitlines():
            line = line.strip()
            if "=" in line:
                cat, pats = line.split("=", 1)
                regex = "(" + pats + ")"
                mask = df[target_col].astype(str).str.contains(regex, case=False, na=False, regex=True)
                df.loc[mask, "카테고리"] = cat.strip()

# ======================================
# 검색 & 필터 (대표자/상호/사업자번호/주민번호)
# ======================================
st.subheader("검색 / 필터")

query = st.text_input("검색할 사업자를 입력해주세요", value="", placeholder="예) 홍길동 111-11-11111 800101-1234567")
match_mode = st.radio("매칭 방식", ["부분 포함(AND)", "부분 포함(OR)"], horizontal=True, index=0)

# 상태 필터
status_options = sorted(df["사업자상태"].dropna().unique().tolist()) if "사업자상태" in df.columns else []
target_status = st.multiselect("사업자상태 필터", options=status_options, default=status_options)

# 폐업 기간 필터 (있을 때만)
date_filter_on = st.checkbox("폐업일자 기간 필터", value=False) if "폐업일자(파싱)" in df.columns else False
start_date = end_date = None
if date_filter_on:
    min_d = pd.to_datetime(df["폐업일자(파싱)"]).min()
    max_d = pd.to_datetime(df["폐업일자(파싱)"]).max()
    c1, c2 = st.columns(2)
    start_date = c1.date_input("시작일", value=min_d.date() if pd.notna(min_d) else None)
    end_date = c2.date_input("종료일", value=max_d.date() if pd.notna(max_d) else None)

# 카테고리 필터
ensure_category()
cat_options = sorted(df["카테고리"].dropna().unique().tolist())
selected_cats = st.multiselect("카테고리 필터", options=cat_options, default=cat_options)

# ======================================
# 검색/필터 적용
# ======================================
working = df.copy()

# 상태 필터
if target_status and "사업자상태" in working.columns:
    working = working[working["사업자상태"].isin(target_status)]

# 폐업 기간 필터 (폐업자에만 적용)
if date_filter_on and start_date and end_date and "폐업일자(파싱)" in working.columns:
    mask = working["폐업일자(파싱)"].notna() & \
           (working["폐업일자(파싱)"] >= pd.to_datetime(start_date)) & \
           (working["폐업일자(파싱)"] <= pd.to_datetime(end_date))
    working = pd.concat([working[mask], working[working.get("사업자상테","사업자상태").ne("폐업", fill_value=True)]]) if "사업자상태" in working.columns else working[mask]

# 카테고리 필터
if selected_cats:
    working = working[working["카테고리"].isin(selected_cats)]

# 검색 로직
if query.strip():
    terms = [t.strip() for t in query.split() if t.strip()]
    working["_사업자번호_숫자"] = working["사업자번호"].apply(digits_only)
    working["_주민번호_숫자"] = working["주민번호"].apply(digits_only)

    def row_match(row) -> bool:
        hay_text = " ".join([
            norm_text(row.get("상호", "")),
            norm_text(row.get("대표자", "")),
            norm_text(row.get("사업자번호", "")),
            norm_text(row.get("주민번호", "")),
        ])
        hay_digits = " ".join([row.get("_사업자번호_숫자", ""), row.get("_주민번호_숫자", "")])

        def contains(term: str) -> bool:
            t_txt = term.lower()
            t_dig = digits_only(term)
            ok_text = (t_txt in hay_text) if t_txt else False
            ok_digit = (t_dig and t_dig in hay_digits)
            return ok_text or ok_digit

        checks = [contains(t) for t in terms]
        return all(checks) if match_mode.startswith("부분 포함(AND)") else any(checks)

    mask = working.apply(row_match, axis=1)
    working = working.loc[mask].drop(columns=[c for c in working.columns if c.startswith("_")], errors="ignore")

# ======================================
# KPI
# ======================================
total_cnt = len(df)
filtered_cnt = len(working)
closed_cnt = (working["사업자상태"] == "폐업").sum() if "사업자상태" in working.columns else 0
active_cnt = (working["사업자상태"] != "폐업").sum() if "사업자상태" in working.columns else 0

k1, k2, k3, k4 = st.columns(4)
k1.metric("전체 행 수(원본)", total_cnt)
k2.metric("필터/검색 결과", filtered_cnt)
k3.metric("계속사업자(결과)", active_cnt)
k4.metric("폐업(결과)", closed_cnt)

# ======================================
# 탭: 요약 / 데이터 / 차트 / 폐업자 목록
# ======================================
tab1, tab2, tab3, tab4 = st.tabs(["📌 요약", "📄 데이터", "📈 차트", "🪪 폐업자 목록"])

with tab1:
    st.subheader("상태 분포")
    if "사업자상태" in working.columns:
        status_counts = working["사업자상태"].value_counts().rename_axis("사업자상태").reset_index(name="건수")
        st.dataframe(status_counts, use_container_width=True)
        if not status_counts.empty:
            st.bar_chart(status_counts.set_index("사업자상태"))

    st.subheader("카테고리 분포")
    cat_counts = working["카테고리"].value_counts().rename_axis("카테고리").reset_index(name="건수")
    st.dataframe(cat_counts, use_container_width=True)
    if not cat_counts.empty:
        st.bar_chart(cat_counts.set_index("카테고리"))

    if "폐업일자(파싱)" in working.columns and "사업자상태" in working.columns:
        st.subheader("폐업 연도별 추이")
        closed_only = working[working["사업자상태"] == "폐업"].copy()
        if not closed_only.empty:
            closed_only["폐업연도"] = pd.to_datetime(closed_only["폐업일자"], errors="coerce").dt.year
            year_counts = closed_only["폐업연도"].dropna().value_counts().sort_index()
            if not year_counts.empty:
                st.bar_chart(year_counts)

with tab2:
    st.subheader("데이터 미리보기")
    view_cols = ["상호", "사업자번호", "대표자", "주민번호", "사업자상태", "폐업일자", "카테고리"]
    view_cols = [c for c in view_cols if c in working.columns]
    st.dataframe(working.reindex(columns=view_cols), use_container_width=True)
    csv_all = working.reindex(columns=view_cols).to_csv(index=False).encode("utf-8-sig")
    st.download_button("⬇️ 필터/검색 결과 CSV 다운로드", data=csv_all, file_name="사업자_현황_결과.csv", mime="text/csv")

with tab3:
    st.subheader("상태×카테고리 교차표")
    if "사업자상태" in working.columns:
        pivot = pd.crosstab(working.get("카테고리", "미분류"), working["사업자상태"]).astype(int)
        st.dataframe(pivot, use_container_width=True)

with tab4:
    st.subheader("폐업자 목록")
    if "사업자상태" in working.columns:
        closed_display = working[working["사업자상태"] == "폐업"]
        cols = ["상호", "사업자번호", "대표자", "주민번호", "사업자상태", "폐업일자", "카테고리"]
        cols = [c for c in cols if c in closed_display.columns]
        st.dataframe(closed_display.reindex(columns=cols), use_container_width=True)
        csv_closed = closed_display.reindex(columns=cols).to_csv(index=False).encode("utf-8-sig")
        st.download_button("⬇️ 폐업자 목록 CSV 다운로드", data=csv_closed, file_name="폐업자_목록.csv", mime="text/csv")

# ======================================
# 안내
# ======================================
with st.expander("안내"):
    st.write(
        "- 검색은 대소문자 구분 없이 부분 일치로 동작합니다.\n"
        "- 사업자번호/주민번호는 하이픈(-) 유무와 관계없이 숫자만 비교 매칭합니다.\n"
        "- 카테고리는 ‘기존 컬럼’ 또는 간단한 ‘키워드 규칙’으로 생성해 필터/집계할 수 있어요."
    )
