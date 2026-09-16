export type BlogChangelogTone = "blue" | "mint" | "gold" | "violet";

export type BlogChangelogEntry = {
	date: string;
	version: string;
	displayDate: string;
	kind: string;
	title: string;
	summary: string;
	details: string[];
	tags: string[];
	tone: BlogChangelogTone;
};

/**
 * 博客本身的建设记录。
 * 记录 Lunox 博客上线以来的页面、内容、视觉和部署变化。
 * 想改文案或补一条新记录，直接往数组顶部加一个对象即可（date 用 YYYY-MM-DD）。
 */
export const blogChangelogEntries: BlogChangelogEntry[] = [
	{
		date: "2026-09-16",
		version: "V1.2.0",
		displayDate: "2026 年 9 月 16 日",
		kind: "视觉与页面迁移",
		title: "把想学的样子，搬进自己的博客",
		summary: "以现有 Firefly 主题为底座，补齐全屏壁纸首页、朋友圈、统计页、动效画廊等一批页面与交互。",
		details: [
			"首页切换为全屏壁纸模式：壁纸随页面正常滚动，去掉暗化遮罩，让照片和站点名片保持原本的亮度。",
			"新增朋友圈页面，构建时抓取友链站点的最近文章，合成一条时间线。",
			"新增站点统计页、博客更新日志页、动态表情画廊和工具页，并把入口整理进导航栏。",
			"右侧边栏加入时段问候、每日一言、年月周进度等小挂件，首页信息密度更完整。",
			"统一全站主题色与卡片样式，页面在不同宽度下都能正常阅读。",
		],
		tags: ["页面", "交互", "视觉", "导航"],
		tone: "mint",
	},
	{
		date: "2026-09-14",
		version: "V1.1.0",
		displayDate: "2026 年 9 月 14 日",
		kind: "作品集与项目文章",
		title: "让作品集真正能装下作品",
		summary: "给作品集加上栏目卡入口和图片瀑布流，并把家装项目写成可以长期更新的项目文章。",
		details: [
			"作品集改为索引页思路：先看到栏目卡，点进去才是完整的图片流。",
			"美术与构成类作品改用瀑布流排布，保留原图比例，不做裁切。",
			"“模型 + 效果图”成对展示的栏目改用统一网格，先定基准列再让其余列等高。",
			"新开项目文章模板，把施工图、建模、效果图、全景图和动画按流程串成一篇。",
		],
		tags: ["作品集", "排版", "项目文章"],
		tone: "gold",
	},
	{
		date: "2026-09-11",
		version: "V1.0.0",
		displayDate: "2026 年 9 月 11 日",
		kind: "建站与部署",
		title: "博客上线",
		summary: "基于 Firefly 主题完成第一次上线，确定站点名称、整体结构和自己写作的栏目。",
		details: [
			"用 Astro + Firefly 主题搭建静态博客，通过 Cloudflare Pages 部署，写作时用 Obsidian 推送到仓库触发更新。",
			"确定站点名称与导航结构，配置页脚、Favicon 和基础 SEO 信息。",
			"接入图床，图片先上传到图床再插入文章，控制整页加载体积。",
			"开启文章目录、代码高亮、阅读时间和卡片式文章列表等阅读体验设置。",
		],
		tags: ["建站", "部署", "主题"],
		tone: "violet",
	},
];
