# ops

- repo-baseline ops 프로필의 도구를 모두 쓴다. 이 파일은 손으로 고치지 않는다. 빼는 도구는 이 파일 끝에 `- 뺀 도구: 도구 — 이유` 한 줄로 적고 그 도구의 줄을 지운다. 다른 도구를 더하려면 먼저 소유자에게 묻는다.
- 코드·의존성 보안(GitHub secret scanning, push protection, Dependabot, CodeQL)은 켜져 있다. CodeQL은 기본 설정을 먼저 쓰고, 기본 설정으로 분석이 안 될 때만 고급 설정 workflow를 쓴다. 그 이유는 저장소 문서에 적는다. 저장소에서 끄지 않는다.
- GitGuardian은 조직에 설치한 GitHub App으로 돈다. 저장소에서 끄지 않는다.
- 에러 추적은 Sentry다.
- 제품 분석은 PostHog다.
- SDK는 처음 배포하는 PR에서 붙인다. 이미 배포한 앱이면 이 파일을 더한 뒤 따로 여는 PR에서 붙인다.
- 배포한 URL은 UptimeRobot에 소유자가 등록한다.
- 도메인은 Cloudflare에 소유자가 연결한다. DNS와 Cloudflare 설정 변경도 소유자가 한다.
- 서버를 직접 운영하게 되면 Grafana Cloud를 켠다. 켜기 전에 소유자에게 알린다.
- 비밀값이 세 곳을 넘으면 Infisical을 켠다. 켜기 전에 소유자에게 알린다.
- Sentry 비밀값 이름은 `SENTRY_DSN`, `SENTRY_AUTH_TOKEN`이다. `.env.example`에 빈 칸으로 둔다. `SENTRY_AUTH_TOKEN`은 GitHub secrets에만 둔다.
- PostHog 비밀값 이름은 `POSTHOG_KEY`, `POSTHOG_HOST`다. `.env.example`에 빈 칸으로 둔다.
- 개인 정보는 분석 이벤트에 넣지 않는다. 세션 녹화를 켜면 입력 필드와 개인 정보를 보여 주는 화면 요소를 가린다.
- SDK를 처음 붙이거나 보내는 데이터를 넓히는 PR은 되돌리기 어려움이다(POLICY §4 다른 사람 데이터의 노출).
- 감시 대상 변경은 소유자가 한다.
