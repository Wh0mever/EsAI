"use client";

import React, { useState, useEffect } from "react";
import { useAppsConfig } from "@/context/AppsConfigContext";
import { useParams } from "next/navigation";
import { Button } from "@/components/UI/Buttons/Buttons";
import { TbLayoutSidebarLeftCollapse } from "react-icons/tb";
import { TbLayoutSidebarLeftExpand } from "react-icons/tb";

interface NavItemProps {
	path: string;
	name?: string;
	appName?: string;
}

interface AppListProps {
	display: string;
	models: {
		[key: string]: {
			display: string;
		};
	};
}

function NavItem({ path, name, appName }: NavItemProps) {
	const isActive = path === appName;
	return (
		<li className="my-2 ms-3 text-sm">
			<a href={`/admin/${path}`} className={`hover:text-blue-500 ${isActive ? "font-bold text-blue-500" : ""}`}>
				{name || path}
			</a>
		</li>
	);
}

function AppList({ appConfig, appName }: { appConfig: AppListProps; appName: string }) {
	return (
		<div>
			<h4 className="text-md text-gray-400">{appConfig.display}</h4>
			<ul>
				{Object.keys(appConfig.models).map((model) => (
					<NavItem
						key={model}
						path={`${appName}/${model}`}
						name={appConfig.models[model].display}
						appName={appConfig.display}
					/>
				))}
			</ul>
		</div>
	);
}

export default function SideBar() {
	const [appsConfig, setAppsConfig] = useState<any>({});
	const [collapsed, setCollapsed] = useState(false);
	const { app } = useParams();

	const appName = (app as string) || "";
	if (!appsConfig) {
		return null;
	}

	const config = useAppsConfig();

	useEffect(() => {
		if (config) {
			setAppsConfig(config);
		}
	}, [config, setAppsConfig]);

	return (
		<aside>
			<div className="flex flex-col w-fit h-screen py-5 border-e border-gray-700 p-4 text-white bg-neutral-950">
				<div className="flex items-center justify-between gap-2">
					<h3 className={`text-lg font-bold text-nowrap ${collapsed ? 'hidden' : ''}`}>Панель администратора</h3>
					<Button onClick={() => {
						setCollapsed(!collapsed);
					}}>
						{collapsed ? (
							<TbLayoutSidebarLeftExpand className="text-xl text-gray-400" />
						) : (
							<TbLayoutSidebarLeftCollapse className="text-xl text-gray-400" />
						)}
					</Button>
				</div>
				<nav className={`flex flex-col gap-2 mt-4 ${collapsed ? "hidden w-fit" : ""}`}>
					{Object.keys(appsConfig).map((app) => {
						const appConfig = appsConfig[app];
						return (
							<div key={app}>
								<AppList appConfig={appConfig} appName={app} />
							</div>
						);
					})}
				</nav>
			</div>
		</aside>
	);
}
