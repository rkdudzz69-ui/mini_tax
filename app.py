# app.py
import io
import re
import pandas as pd
import streamlit as st

# ==============================
# 공통 설정
# ==============================
st.set_page_config(page_title="사업자 대시보드", layout="wide")
st.title("사업자 대시보드")

# 예시 데이터 (업로드 없을 때 사용)
SAMPLE_DATA = {
    "상호": ["A상사", "B무역", "C식당", "D전자", "E상점", "F기업", "G상회"],
    "사업자번호": ["111-11-11111", "222-22-22222", "333-33-33333", "444-44-44444", "555-55-55555", "666-66-66666", "777-77-77777"],
    "대표자": ["홍길동", "김철수", "이영희", "박민수", "최유진", "정다혜", "오성민"],
    "주민번호": ["800101-1234567", "820202-2345678", "830303-3456789", "840404-4567890", "850505-5678901", "860606-6789012", "870707-7890123"],
    "사업자상태": ["계속사업자", "폐업", "폐업", "계속사업자", "폐업", "계속사업자", "계속사업자"],
    "폐업일자": ["", "2020-03-01", "2021-05-10", "", "2023-01-30", "", ""],
    # 있으면 그대로 쓰는 카테고리 컬럼(없어도 됨)
    # "카테고리": ["도소매", "무역", "외식", "전자", "소매", "도소매", "도소매"]
}

# ==============================
# 공통 유틸
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

# ==============================
# 데이터 로드(공통)
# ==============================
file = st.file_uploader("사업내역 파일 업로드 (.xlsx, .xls, .csv)", type=["xlsx", "xls", "csv"])
if file:
    df = load_df_from_file(file)
else:
    st.info("업로드가 없어서 예시 데이터를 사용 중이야. 실제 파일을 올리면 그걸로 분석해!")
    df = pd.DataFrame(SAMPLE_DATA)

df = normalize_cols(df)

# 공통 필수 컬럼 체크
required = {"상호", "사업자번호", "대표자", "주민번호"}
missing = [c for c in required if c not in df.columns]
if missing:
    st.error(f"필수 컬럼이 없어요: {', '.join(missing)}")
    st.stop()

# ==============================
# 페이지 스위처
# ==============================
page = st.sidebar.selectbox(
    "화면 선택",
    ("OpenAI 메인(검색)", "전체 폐업자 현황(카테고리)")
)

# ==============================
# ① OpenAI 메인(검색)
# ==============================
def page_openai_main(df: pd.DataFrame):
    st.header("사업자 현황 (OpenAI 메인)")
    st.caption("검색할 사업자를 입력해주세요 · 대표자/상호/사업자번호/주민번호 전체에서 부분 일치로 검색돼요.")

    # 검색 UI
    query = st.text_input("검색할 사업자를 입력해주세요", value="", placeholder="예) 홍길동 111-11-11111 800101-1234567")
    match_mode = st.radio("매칭 방식", ["부분 포함(AND)", "부분 포함(OR)"], horizontal=True)

    # 검색 로직
    if query.strip():
        terms = [t.strip() for t in query.split() if t.strip()]
        df["_사업자번호_숫자"] = df["사업자번호"].apply(digits_only)
        df["_주민번호_숫자"] = df["주민번호"].apply(digits_only)

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

        mask = df.apply(row_match, axis=1)
        result = df.loc[mask].drop(columns=[c for c in df.columns if c.startswith("_")], errors="ignore")
    else:
        result = df.copy()

    # KPI & 결과
    c1, c2 = st.columns(2)
    c1.metric("전체 행 수", len(df))
    c2.metric("검색 결과 수", len(result))

    view_cols = ["상호", "사업자번호", "대표자", "주민번호", "사업자상태", "폐업일자"]
    view_cols = [c for c in view_cols if c in result.columns]
    st.subheader("검색 결과")
    st.dataframe(result.reindex(columns=view_cols), use_container_width=True)

    csv_bytes = result.reindex(columns=view_cols).to_csv(index=False).encode("utf-8-sig")
    st.download_button("⬇️ 검색 결과 CSV 다운로드", data=csv_bytes, file_name="검색_결과.csv", mime="text/csv")

    with st.expander("안내"):
        st.write(
            "- 검색은 대소문자 구분 없이 부분 일치로 동작해.\n"
            "- 사업자번호/주민번호는 하이픈(-) 유무와 상관없이 숫자만 비교해서 찾아줘.\n"
            "- 여러 키워드는 공백으로 나눠서 AND/OR 모드로 사용할 수 있어."
        )

# ==============================
# ② 전체 폐업자 현황(카테고리)
# ==============================
def page_closed_with_category(df: pd.DataFrame):
    st.header("전체 폐업자 현황 (카테고리)")
    # 폐업일자 파싱
    if "폐업일자" in df.columns:
        df["폐업일자"] = df["폐업일자"].replace({"": pd.NA})
        df["폐업일자(파싱)"] = pd.to_datetime(df["폐업일자"], errors="coerce")

    # 사이드바 필터
    st.sidebar.subheader("폐업 필터")
    date_filter_on = st.sidebar.checkbox("폐업일자 기간으로 필터", value=False)
    start_date = end_date = None
    if date_filter_on and "폐업일자(파싱)" in df.columns:
        min_d = pd.to_datetime(df["폐업일자(파싱)"]).min()
        max_d = pd.to_datetime(df["폐업일자(파싱)"]).max()
        c1, c2 = st.sidebar.columns(2)
        start_date = c1.date_input("시작일", value=min_d.date() if pd.notna(min_d) else None)
        end_date = c2.date_input("종료일", value=max_d.date() if pd.notna(max_d) else None)

    # 카테고리 생성/선택
    st.sidebar.subheader("카테고리 설정")
    cat_mode = st.sidebar.radio("방식", ["기존 컬럼 사용", "키워드 규칙"], index=0)

    # 1) 기존 컬럼 사용
    if cat_mode == "기존 컬럼 사용":
        candidates = [c for c in df.columns if any(k in c for k in ["카테고리", "업종", "업태", "지역", "분류"])]
        if candidates:
            cat_col = st.sidebar.selectbox("카테고리로 쓸 컬럼", candidates, index=0)
            df["카테고리"] = df[cat_col].astype(str).str.strip()
        else:
            st.sidebar.info("추천 컬럼이 없어 임시 ‘카테고리=미분류’를 사용함")
            df["카테고리"] = "미분류"

    # 2) 키워드 규칙 (대상 컬럼 기본: 상호)
    else:
        rule_text = st.sidebar.text_area(
            "규칙 입력 (예: 전자상거래=전자|온라인 / 외식=식당|요리 / 도소매=상사|상회)",
            value="전자상거래=전자|온라인\n외식=식당|요리\n도소매=상사|상회",
            height=120
        )
        target_col = st.sidebar.selectbox("규칙 적용 대상 컬럼", options=[c for c in df.columns], index=([c for c in df.columns].index("상호") if "상호" in df.columns else 0))
        df["카테고리"] = "미분류"
        if rule_text.strip():
            for line in rule_text.splitlines():
                line = line.strip()
                if "=" in line:
                    cat, pats = line.split("=", 1)
                    regex = "(" + pats + ")"
                    mask = df[target_col].astype(str).str.contains(regex, case=False, na=False, regex=True)
                    df.loc[mask, "카테고리"] = cat.strip()

    # 실제 폐업만 필터
    filtered = df[df.get("사업자상태", "").astype(str).str.strip() == "폐업"].copy()
    if date_filter_on and start_date and end_date and "폐업일자(파싱)" in filtered.columns:
        mask = (filtered["폐업일자(파싱)"] >= pd.to_datetime(start_date)) & (filtered["폐업일자(파싱)"] <= pd.to_datetime(end_date))
        filtered = filtered[mask]

    # KPI
    c1, c2, c3 = st.columns(3)
    c1.metric("전체 행 수", len(df))
    c2.metric("폐업 행 수", len(filtered))
    c3.metric("카테고리 수", filtered["카테고리"].nunique() if "카테고리" in filtered.columns else 0)

    # 표 & 다운로드
    st.subheader("폐업자 목록")
    view_cols = ["상호", "사업자번호", "대표자", "주민번호", "사업자상태", "폐업일자", "카테고리"]
    view_cols = [c for c in view_cols if c in filtered.columns]
    st.dataframe(filtered.reindex(columns=view_cols), use_container_width=True)

    csv_bytes = filtered.reindex(columns=view_cols).to_csv(index=False).encode("utf-8-sig")
    st.download_button("⬇️ 폐업자 목록(CSV) 다운로드", data=csv_bytes, file_name="폐업자_목록.csv", mime="text/csv")

    # 요약/차트
    st.subheader("카테고리 분포")
    if "카테고리" in filtered.columns and not filtered.empty:
        counts = filtered["카테고리"].value_counts().rename_axis("카테고리").reset_index(name="건수")
        st.dataframe(counts, use_container_width=True)
        if not counts.empty:
            st.bar_chart(counts.set_index("카테고리"))

    with st.expander("안내"):
        st.write(
            "- ‘기존 컬럼 사용’은 파일에 있는 카테고리/업종/지역 등 컬럼을 그대로 씀.\n"
            "- ‘키워드 규칙’은 `카테고리=키워드1|키워드2` 형식으로 간단 분류 가능."
        )

# ==============================
# 라우팅
# ==============================
if page == "OpenAI 메인(검색)":
    page_openai_main(df)
else:
    page_closed_with_category(df)
