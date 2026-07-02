"""Internationalization strings for the frontend UI."""

SUPPORTED_LANGUAGES = {"en-US": "English", "ko-KR": "한국어"}

STARTERS = {
    "en-US": [
        {
            "label": "Upload a document",
            "message": "Upload a document for research",
            "icon": "/public/images/upload.png",
        },
        {
            "label": "Summarize with citations",
            "message": (
                "Analyze the key findings and provide a comprehensive, business and technical value-added "
                "summary with citations."
            ),
            "icon": "/public/images/search.png",
        },
        {
            "label": "Compare arguments",
            "message": (
                "Compare and contrast the main arguments presented, business and technical value-added "
                "in the uploaded documents."
            ),
            "icon": "/public/images/compare.png",
        },
    ],
    "ko-KR": [
        {
            "label": "문서 업로드",
            "message": "리서치를 위한 문서를 업로드합니다",
            "icon": "/public/images/upload.png",
        },
        {
            "label": "인용 포함 요약",
            "message": (
                "핵심 내용을 분석하고 사업적, 기술적 가치 두 측면에 대해 인용을 포함한 "
                "종합적인 요약을 제공해주세요."
            ),
            "icon": "/public/images/search.png",
        },
        {
            "label": "논점 비교",
            "message": (
                "업로드된 문서에 제시된 주요 논점들을 사업적, 기술적 가치 두 측면에 대해 "
                "비교 분석해주세요."
            ),
            "icon": "/public/images/compare.png",
        },
    ],
}

SYSTEM_PROMPT_LANGUAGE = {
    "en-US": "You MUST respond entirely in English.",
    "ko-KR": "반드시 한국어로 답변하세요.",
}
