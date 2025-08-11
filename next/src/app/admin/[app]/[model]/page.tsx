"use client";
import React, { useState, useEffect } from "react";
import { AppTable } from "@/components/admin/AppTable/AppTable";
import { useParams } from "next/navigation";
import { useAppsConfig } from "@/context/AppsConfigContext";
import { Loader } from "@/components/global/Loader";

export default function AdminPage() {
	const params = useParams();
	const appName = (params as any).app || "";
	const modelName = (params as any).model || "";
	const [appsConfig, setAppsConfig] = useState<any>(null);

	const config = useAppsConfig();

	useEffect(() => {
		if (config) {
			setAppsConfig(config);
		}
	}, [config, setAppsConfig]);

	return (
		<>
			{appsConfig ? (
				<AppTable appName={appName} modelName={modelName} />

			) : (
				<div className="flex justify-center items-center h-screen">
					<Loader />
				</div>
			)}
		</>
	);
}
