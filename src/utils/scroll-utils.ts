import { BANNER_HEIGHT } from "@/constants/constants";
import { isBannerMode } from "@/utils/banner-utils";
import { updateSidebarStickySpacing } from "@/utils/grid-layout-utils";

const backToTopBtn = document.getElementById("back-to-top-btn");
const toc = document.getElementById("toc-wrapper");
const navbar = document.getElementById("navbar-wrapper");

/** 滚动方向容差（px）：小于该幅度的抖动不改变导航栏显隐，避免触控板微抖闪烁 */
const NAVBAR_DIRECTION_TOLERANCE = 6;
/** 抵达内容区顶部后再多滚多少才隐藏导航栏（px） */
const NAVBAR_HIDE_BUFFER = 40;
/**
 * 全屏模式下非首页自动回落到内容区顶部时，内容区停靠位置 = 内容区顶部 - 5.5rem。
 * 判断阈值要对齐到这个“落地点”，否则刚进文章页（已经在 contentTop-88）就会立刻隐藏。
 */
const NAVBAR_LANDING_OFFSET = 88;

/** 上一次滚动位置，用于判断滚动方向 */
let lastNavbarScrollTop = 0;

/**
 * 导航栏自动隐藏阈值：滚过这个位置之后，向下滚隐藏、向上滚显示。
 * - 首页：内容区排在整张壁纸下方，滚过内容区顶部（壁纸全部滚走）再多滚一点才隐藏；
 * - 内页：全屏模式跳转后视口已停在内容区顶部（contentTop - 88），从落地点再滚一点即可。
 */
function resolveNavbarHideThreshold(contentTop: number): number {
	const isHome = document.body.classList.contains("is-home");
	if (isHome) {
		return Math.max(contentTop, 0) + NAVBAR_HIDE_BUFFER;
	}
	return Math.max(contentTop - NAVBAR_LANDING_OFFSET, 0) + NAVBAR_HIDE_BUFFER;
}

/** 导航栏浮层（显示设置 / 移动菜单 / 音乐面板）展开时不隐藏，避免面板被一起带走 */
function hasOpenNavbarPanel(): boolean {
	const panels = ["display-setting", "nav-menu-panel", "music-nav-panel"];
	return panels.some((id) => {
		const panel = document.getElementById(id);
		return !!panel && !panel.classList.contains("float-panel-closed");
	});
}

/** 优化的滚动处理函数（从 Layout.astro 迁出；visit:end 切页后也会调用） */
export function scrollFunction(): void {
	if (document.documentElement.classList.contains("is-page-transitioning")) {
		return;
	}

	const scrollTop = document.documentElement.scrollTop;
	const bannerHeight = window.innerHeight * (BANNER_HEIGHT / 100);
	const navbarElement = document.getElementById("navbar");

	// 本次与上次的滚动位移，用于判断滚动方向（自动隐藏导航栏）
	const prevNavbarScrollTop = lastNavbarScrollTop;
	lastNavbarScrollTop = scrollTop;

	// 根据滚动位置动态更新侧边栏 sticky 间距
	updateSidebarStickySpacing();

	// 使用批量DOM操作优化性能
	const operations: (() => void)[] = [];

	if (backToTopBtn) {
		operations.push(() => {
			if (scrollTop > bannerHeight) {
				backToTopBtn.classList.remove("hide");
			} else {
				backToTopBtn.classList.add("hide");
			}
		});
	}

	if (isBannerMode() && toc) {
		operations.push(() => {
			if (scrollTop > bannerHeight) {
				toc.classList.remove("toc-hide");
			} else {
				toc.classList.add("toc-hide");
			}
		});
	}

	if (navbar) {
		operations.push(() => {
			// 导航栏自动隐藏（对齐原帖）：滚过内容区顶部之后，向下滚收起、向上滚展开
			const contentPanel = document.querySelector(
				".content-panel",
			) as HTMLElement | null;
			const contentTop = contentPanel
				? contentPanel.getBoundingClientRect().top + scrollTop
				: 0;
			const hideThreshold = resolveNavbarHideThreshold(contentTop);
			const scrollDelta = scrollTop - prevNavbarScrollTop;

			if (scrollTop <= hideThreshold || hasOpenNavbarPanel()) {
				// 还没滚到该隐藏的位置（刚进页面 / 回到顶部），或浮层展开中：始终显示
				navbar.classList.remove("navbar-hidden");
				return;
			}
			if (scrollDelta > NAVBAR_DIRECTION_TOLERANCE) {
				navbar.classList.add("navbar-hidden");
			} else if (scrollDelta < -NAVBAR_DIRECTION_TOLERANCE) {
				navbar.classList.remove("navbar-hidden");
			}
		});
	}

	if (navbarElement) {
		operations.push(() => {
			if (scrollTop > 8) {
				navbarElement.classList.add("navbar-sticky-shadow");
			} else {
				navbarElement.classList.remove("navbar-sticky-shadow");
			}
		});
	}

	// 批量执行DOM操作
	if (operations.length > 0) {
		requestAnimationFrame(() => {
			operations.forEach((op) => {
				op();
			});
		});
	}
}

let scrollTimeout: number;

/** 注册滚动 / 窗口尺寸监听并初始化滚动状态（从 Layout.astro 迁出） */
export function initScroll(): void {
	// 使用优化的滚动性能处理
	window.addEventListener(
		"scroll",
		() => {
			if (scrollTimeout) {
				cancelAnimationFrame(scrollTimeout);
			}
			scrollTimeout = requestAnimationFrame(scrollFunction);
		},
		{ passive: true },
	);

	// 初始化滚动状态（例如从历史位置恢复时）
	scrollFunction();
}
