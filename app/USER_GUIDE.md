# COS Lab 설치와 실행

## 설치

1. [Windows 설치용 ZIP](https://github.com/tjdbf061106-sketch/COS_project/releases/download/coslab-v0.3.0/COSLab-0.3.0-Windows.zip)을 다운로드합니다.
2. 원하는 위치에 ZIP **전체를 압축 해제**합니다.
3. 압축을 푼 `COSLab-0.3.0` 폴더를 엽니다.
4. **`Install-COSLab.bat`를 더블클릭**합니다.
5. 설치 완료 후 바탕화면의 **COS Lab** 바로가기를 실행합니다.

Windows 10/11 x64용입니다. Python과 피부·눈 분석 엔진이 포함되어 있습니다. 설치는 현재 사용자 계정에 진행되며 관리자 권한을 요구하지 않습니다.

설치 없이 실행하려면 압축을 푼 폴더의 `COSLab.exe`를 실행하세요. 실행파일과 함께 있는 `_internal`, `engines` 폴더도 필요합니다.

## 처음 사용하기

앱에서 **예제 불러오기 → 분석**을 선택하면 6개 원료의 피부·눈 점수와 원료별 구조·보조점수를 확인할 수 있습니다. 보고서는 JSON·CSV·PDF로 저장할 수 있습니다.

기본 예제 분석은 인터넷 없이 가능합니다. 사전에 없는 성분명 검색과 추가 PubChem 주석 조회는 인터넷이 필요합니다.

## 업데이트

앱을 종료하고 새 ZIP을 압축 해제한 뒤 `Install-COSLab.bat`를 다시 실행합니다. 설치 위치는 `%LOCALAPPDATA%\Programs\COSLab`, 사용자 저장자료 위치는 `%LOCALAPPDATA%\COSLab`입니다.

연구용 예측 앱이며 제품의 안전성이나 질환별 사용 가능 여부를 판정하지 않습니다. [소스와 재현 안내](https://github.com/tjdbf061106-sketch/COS_project/tree/main/app)도 함께 제공합니다.
