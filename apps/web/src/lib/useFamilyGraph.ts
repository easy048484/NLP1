import { useEffect } from "react";
import { useApp } from "./appState";
import { getFamilyGraph } from "./familyGraph";

/**
 * familyGraphId가 있는데 아직 그래프 본문을 안 들고 있으면 한 번 불러와
 * 앱 상태에 채운다. 컨텍스트 패널·가족트리가 공유한다.
 */
export function useFamilyGraphSync(): void {
  const { familyGraphId, familyGraph, setFamilyGraph, setFamilyGraphId } = useApp();

  useEffect(() => {
    if (!familyGraphId || familyGraph?.id === familyGraphId) return;
    let cancelled = false;
    (async () => {
      const res = await getFamilyGraph(familyGraphId);
      if (cancelled) return;
      if (res.ok && res.data) {
        setFamilyGraph(res.data);
      } else if (res.status === 404) {
        // 저장된 id 가 서버에서 사라짐(배포 시 DB 재생성 등) → 지워서
        // 이후 인테이크·패널이 새 그래프를 만들게 한다.
        setFamilyGraphId(null);
        setFamilyGraph(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [familyGraphId, familyGraph?.id, setFamilyGraph, setFamilyGraphId]);
}
