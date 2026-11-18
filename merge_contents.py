import json

# 기존 콘텐츠 불러오기
with open("contents.json", "r", encoding="utf-8") as f:
    contents = json.load(f)

# OTT 콘텐츠 불러오기
with open("ott_contents.json", "r", encoding="utf-8") as f:
    ott_contents = json.load(f)

# 데이터 통합 및 중복 제거
merged = {}

for content in contents + ott_contents:
    key = (content["type"], content["id"])

    merged.setdefault(key, {}).update(content)

result = list(merged.values())

# 통합 데이터 저장
with open("merged_contents.json", "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print(f"기존 콘텐츠: {len(contents)}개")
print(f"OTT 콘텐츠: {len(ott_contents)}개")
print(f"중복 제거: {len(contents) + len(ott_contents) - len(result)}개")
print(f"최종 콘텐츠: {len(result)}개")
print("데이터 통합 완료!")