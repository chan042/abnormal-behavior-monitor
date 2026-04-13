# Frontend Dashboard

이 프론트엔드는 CCTV 이상행동 관제 대시보드를 위한 `Next.js` 앱이다.

현재 구조:
- `Next.js App Router`
- `React`
- `Tailwind CSS v4`
- 백엔드 API 프록시 대상: `FastAPI`

## 실행

권장 런타임:
- Node.js `22` LTS 권장 (`frontend/.nvmrc` 참고)
- Python 가상환경 `.venv`

1. 백엔드 실행

```bash
python3 -m backend.app.main serve-fastapi --host 127.0.0.1 --port 8100
```

2. 프론트 실행

개발 서버 메모리를 줄이려면 프런트가 FastAPI를 직접 호출하도록 환경 변수를 주는 편이 낫다.
이렇게 하면 브라우저 라이브 프레임 POST가 Next.js 프록시를 거치지 않는다.

```bash
cd frontend
nvm use
npm install
NEXT_PUBLIC_BACKEND_ORIGIN=http://127.0.0.1:8100 npm run dev
```

3. 브라우저에서 `http://127.0.0.1:3000` 접속

기본적으로 `npm run dev` 는 `next dev --webpack` 으로 실행된다.
메모리가 특히 빠듯하면 개발 서버 대신 프로덕션 모드로 여는 편이 더 안정적이다.

```bash
cd frontend
nvm use
npm install
npm run build
npm run start
```

가장 높은 메모리 사용 가능성이 있는 조합:
- `next dev` 기본 Turbopack
- `NEXT_PUBLIC_BACKEND_ORIGIN` 없이 `/api/browser-live/frame` 을 Next 프록시로 중계
- 브라우저 카메라 라이브를 켠 상태에서 장시간 실행

기본적으로 프론트의 `/api/*` 요청은 `http://127.0.0.1:8100/api/*` 로 프록시된다.
다른 백엔드 주소를 쓰려면 다음 둘 중 하나를 사용하면 된다.

- 브라우저에서 직접 호출: `NEXT_PUBLIC_BACKEND_ORIGIN=http://127.0.0.1:8100`
- Next.js 리라이트 프록시: `BACKEND_ORIGIN=http://127.0.0.1:8100`

Turbopack 경로가 필요하면 아래처럼 명시적으로만 사용한다.

```bash
npm run dev:turbopack
```

검증용 빌드는 webpack 경로를 기본값으로 둔다.

```bash
npm run build
```

## 주요 화면

- `실시간 관제`
- `이벤트 검토`
- `통계/분석`
- `설정`

카메라 상태 정보는 대시보드 내부에서 제공되지만, 현재는 별도 최상위 메뉴로 분리되어 있지 않다.

## 브라우저 카메라 라이브 검증

1. `실시간 관제` 화면으로 이동
2. `브라우저 카메라 라이브` 패널에서 카메라 권한 허용
3. 맥 카메라 또는 아이폰 Continuity Camera 선택
4. `카메라 열기` 클릭
5. YOLO 박스, MediaPipe 스켈레톤, 이벤트 배지가 실시간으로 표시되는지 확인

## 검증

- `npm run lint`
- `npm run build`
- `npm run build:turbopack`
