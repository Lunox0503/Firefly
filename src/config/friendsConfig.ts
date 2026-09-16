import type { FriendLink, FriendsPageConfig } from "../types/friendsConfig";

// 可以在src/content/spec/friends.md中编写友链页面下方的自定义内容

// 友链页面配置
export const friendsPageConfig: FriendsPageConfig = {
	// 页面标题，如果留空则使用 i18n 中的翻译
	title: "",

	// 页面描述文本，如果留空则使用 i18n 中的翻译
	description: "",

	// 是否显示底部自定义内容（friends.mdx 中的内容）
	showCustomContent: true,

	// 是否显示评论区，需要先在commentConfig.ts启用评论系统
	showComment: true,

	// 是否开启随机排序配置，如果开启，就会忽略权重，构建时进行一次随机排序
	randomizeSort: false,
};

// 友链配置
export const friendsConfig: FriendLink[] = [
	{
		title: "夏夜流萤",
		imgurl:
			"https://weavatar.com/avatar/d252655d40d6874417a720bad0a6c5f77f8f6a1fd2f882f8f338402dc37e4190?s=640",
		desc: "飞萤之火自无梦的长夜亮起，绽放在终竟的明天。",
		siteurl: "https://blog.cuteleaf.cn",
		tags: ["Blog"],
		weight: 10, // 权重，数字越大排序越靠前
		enabled: true, // 是否启用
	},
	{
		title: "Firefly Docs",
		imgurl: "https://docs-firefly.cuteleaf.cn/logo.png",
		desc: "Firefly主题模板文档",
		siteurl: "https://docs-firefly.cuteleaf.cn",
		tags: ["Docs"],
		weight: 9,
		enabled: true,
	},
	{
		title: "Astro",
		imgurl: "https://avatars.githubusercontent.com/u/44914786?v=4&s=640",
		desc: "The web framework for content-driven websites. ⭐️ Star to support our work!",
		siteurl: "https://github.com/withastro/astro",
		tags: ["Framework"],
		weight: 8,
		enabled: true,
	},
];

// 已加入的博客项目（友链页面顶部的"我参加的博客社区/项目"展示区）
export const friendsProjects: FriendLink[] = [
	{
		title: "博友圈",
		imgurl: "https://www.boyouquan.com/assets/images/sites/logo/logo-small.png",
		desc: "让我们跨越山海彼此相连，一起用文字打败时间！",
		siteurl: "https://www.boyouquan.com/home",
		tags: ["博客社区", "友链互推", "RSS"],
		weight: 40,
		enabled: true,
	},
	{
		title: "博客星球",
		imgurl: "https://www.blogplanet.cn/img/bkxq.png",
		desc: "每一个博客都是一个独立星球！",
		siteurl: "https://www.blogplanet.cn/",
		tags: ["博客社区", "博客收录", "博主交流"],
		weight: 30,
		enabled: true,
	},
	{
		title: "BlogsClub",
		imgurl: "https://www.blogsclub.org/usr/themes/default/favicon.png",
		desc: "BlogsClub 是一个互联网独立博客俱乐部。",
		siteurl: "https://www.blogsclub.org/",
		tags: ["博客社区", "博主交流", "博客收录"],
		weight: 10,
		enabled: true,
	},
];

// 获取启用的友链并进行排序
export const getEnabledFriends = (): FriendLink[] => {
	const friends = friendsConfig.filter((friend) => friend.enabled);

	if (friendsPageConfig.randomizeSort) {
		return friends.sort(() => Math.random() - 0.5);
	}

	return friends.sort((a, b) => b.weight - a.weight);
};
