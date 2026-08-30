import { useEffect } from "react";
import { useApp } from "./appState";
import { getFamilyGraph } from "./familyGraph";

/**
 * familyGraphId가 있는데 아직 그래프 본문을 안 들고 있으면 한 번 불러와
 * 앱 상태에 채운다. 컨텍스트 패널·가족트리가 공유한다.
 */
export function useFamilyGraphSync(): void {
  const { familyGraphId, familyGraph, setFamilyGraph } = useApp();

  useEffect(() => {
    if (!familyGraphId || familyGraph?.id === familyGraphId) return;
    let cancelled = false;
    (async () => {
      const res = await getFamilyGraph(familyGraphId);
      if (!cancelled && res.ok && res.data) setFamilyGraph(res.data);
    })();
    return () => {
      cancelled = true;
    };
  }, [familyGraphId, familyGraph?.id, setFamilyGraph]);
}
