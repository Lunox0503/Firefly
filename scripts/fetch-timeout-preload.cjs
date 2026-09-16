/**
 * 构建期 fetch 超时保护（仅通过 NODE_OPTIONS --require 注入，不影响站点运行时）。
 *
 * 背景：本机构建走本地代理，一旦代理/网络瞬断，构建中的某个 fetch 可能
 * 永远挂起（连接建立但无响应、且无超时），导致 astro build 卡死（CPU 0%）。
 * 这里给全局 fetch 包一层 AbortSignal.timeout，让任何挂起的请求在超时后失败，
 * 使构建继续（或走已有兜底逻辑），而不是无限卡住。
 */
const FETCH_TIMEOUT_MS = 90_000;

const originalFetch = globalThis.fetch;
if (typeof originalFetch === "function") {
	globalThis.fetch = function timeoutFetch(input, init = {}) {
		try {
			if (!init.signal) {
				init = { ...init, signal: AbortSignal.timeout(FETCH_TIMEOUT_MS) };
			}
		} catch {
			// AbortSignal 不可用时退回原生行为
		}
		return originalFetch(input, init);
	};
}
