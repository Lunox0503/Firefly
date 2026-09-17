<script lang="ts">
import { onDestroy, onMount } from "svelte";
import { musicPlayerConfig } from "@/config/musicConfig";
import { AudioAnalyzer } from "./AudioAnalyzer";
import LyricsOverlay from "./LyricsOverlay.svelte";
import ThreeScene from "./ThreeScene.svelte";
import VisualizerControls from "./VisualizerControls.svelte";

const audioAnalyzer = new AudioAnalyzer();
let sceneReady = $state(false);
let backgroundColor = $state(
	musicPlayerConfig.visualizer?.background?.dark ?? "#0a0a15",
);

function syncPageBackground() {
	backgroundColor = document.documentElement.classList.contains("dark")
		? (musicPlayerConfig.visualizer?.background?.dark ?? "#0a0a15")
		: (musicPlayerConfig.visualizer?.background?.light ?? "#2D2D2D");
}

function connectAudio() {
	const audio = document.getElementById(
		"firefly-music-audio",
	) as HTMLAudioElement | null;
	if (!audio) {
		setTimeout(connectAudio, 200);
		return;
	}
	// 尝试连接 Web Audio API
	// 注意：crossOrigin 需要在 audio src 设置之前设置才有效
	// 如果音频源不支持 CORS，Web Audio 分析会静默失败，但音频仍能正常播放
	if (!audio.crossOrigin) {
		audio.crossOrigin = "anonymous";
	}
	try {
		audioAnalyzer.connect(audio);
	} catch (e) {
		console.warn("[MusicVisualizer] AudioAnalyzer connect failed:", e);
	}

	if (audioCtxState() === "suspended") {
		audioAnalyzer.resume();
	}
}

function audioCtxState() {
	return audioAnalyzer.audioCtx?.state || "running";
}

onMount(() => {
	syncPageBackground();

	const themeObserver = new MutationObserver(syncPageBackground);
	themeObserver.observe(document.documentElement, {
		attributes: true,
		attributeFilter: ["class"],
	});

	const mgr = window.__fireflyMusic;
	if (!mgr) {
		const waitForMgr = () => {
			if (window.__fireflyMusic) {
				connectAudio();
			} else {
				setTimeout(waitForMgr, 100);
			}
		};
		waitForMgr();
	} else {
		if (!mgr.getState().initialized) {
			mgr.init();
		}
		connectAudio();
	}

	const handleFirstClick = () => {
		audioAnalyzer.resume();
		document.removeEventListener("click", handleFirstClick);
	};
	document.addEventListener("click", handleFirstClick);

	return () => {
		themeObserver.disconnect();
		document.removeEventListener("click", handleFirstClick);
	};
});

onDestroy(() => {
	audioAnalyzer.disconnect();
});
</script>

<div class="music-visualizer" style={`background: ${backgroundColor};`}>
	{#if sceneReady}
		<VisualizerControls />
		<LyricsOverlay />
	{/if}
	<ThreeScene
		{audioAnalyzer}
		{backgroundColor}
		onSceneReady={() => (sceneReady = true)}
	/>
</div>
