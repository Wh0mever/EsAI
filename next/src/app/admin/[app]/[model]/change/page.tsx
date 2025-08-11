"use client";
import React, { useState, useEffect } from "react";
import { AppTable } from "@/components/admin/AppTable/AppTable";
import { useParams } from "next/navigation";
import { useAppsConfig } from "@/context/AppsConfigContext";
import { Loader } from "@/components/global/Loader";
import { fetchData } from "@/tools/fetchData";
import AppForm from "@/components/admin/AppForm/AppForm";

export default function AdminPage() {
	const params = useParams();
	const appName = (params as any).app || "";
	const modelName = (params as any).model || "";
	const [appsConfig, setAppsConfig] = useState<any>(null);
	const [fieldsConfig, setFieldsConfig] = useState<any>(null);

	const config = useAppsConfig();

	useEffect(() => {
		if (config) {
			setAppsConfig(config);
		}
	}, [config, setAppsConfig]);

	useEffect(() => {
		fetchData(`admin/fields/${appName}/${modelName}/`, 'GET')
		.then((data) => {
			setFieldsConfig(data);
		})
		.catch((error) => {
			console.error("Error fetching table data:", error);

		});
	}, [appName, setFieldsConfig]);

	return (
		<>
			<AppForm fieldsConfig={fieldsConfig} />
		</>
	);
}
