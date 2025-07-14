"use client";

import React, { useState, useEffect } from "react";
import { fetchData } from "@/tools/fetchData";
import { useParams } from "next/navigation";
import { Loader } from "@/components/UI/Loader/Loader";
import { useAppsConfig } from "@/context/AppsConfigContext";
import { Button } from "@/components/UI/Buttons/Buttons";
import { CiCirclePlus, CiExport } from "react-icons/ci";
import { GoTriangleDown, GoTriangleUp } from "react-icons/go";
import NextLink from "@/components/UI/NextLink/NextLink";

interface TableData {
	data: any[];
	fields_display: any;
}

const Th = ({ children }: { children: any }) => {
	return (
		<th className="px-6 py-3 text-left text-xs font-medium border border-gray-600 text-gray-300 capitalize text-nowrap">
			{children}
		</th>
	);
};

const Td = ({ children }: { children: any }) => {
	return <td className="px-6 py-4 whitespace-nowrap text-sm border border-gray-600 text-white">{children}</td>;
};

const THead = ({ tableData }: { tableData: any }) => {
	return (
		<thead>
			<tr className="bg-neutral-900">
				<Th>
					<input type="checkbox" />
				</Th>
				{Object.keys(tableData.data[0] || {}).map((key) => (
					<Th key={key}>
						<div className="flex gap-2 items-center">
							{tableData.fields_display[key]}
							<div className="flex flex-col">
								<div className="flex gap-1">
									<Button
										type="button"
										className="bg-neutral-800 text-white px-2 py-1 rounded-md hover:text-blue-500"
										onClick={() => {}}
									>
										<GoTriangleUp />
									</Button>
									<Button
										type="button"
										className="bg-neutral-800 text-white px-2 py-1 rounded-md hover:text-blue-500"
										onClick={() => {}}
									>
										<GoTriangleDown />
									</Button>
								</div>
							</div>
						</div>
					</Th>
				))}
			</tr>
		</thead>
	);
};

const TBody = ({ tableData }: { tableData: any }) => {
	return (
		<tbody>
			{tableData.data.map((item: any, index: number) => (
				<tr key={index}>
					<Td>
						<input type="checkbox" />
					</Td>
					{Object.keys(item).map((key) => (
						<Td key={key}>{item[key]}</Td>
					))}
				</tr>
			))}
		</tbody>
	);
};

const Table = ({ tableData }: { tableData: any }) => {
	if (!tableData || !tableData.data || !tableData.data.length) {
		return <div className="flex-auto">Данные не найдены</div>;
	}

	return (
		<table className="">
			<THead tableData={tableData} />
			<TBody tableData={tableData} />
		</table>
	);
};

const ActionsHeader = ({ appName, modelName, appConfig }: { appName: string; modelName: string; appConfig: any }) => {
	return (
		<>
			<div className="flex gap-2">
				<h3 className="text-lg font-bold text-nowrap">{appConfig && appConfig[appName].display}</h3>
			</div>
			<div className="flex gap-2">
				<Button
					onClick={() => {}}
					className="bg-neutral-800 text-white px-4 py-2 flex items-center gap-2 hover:bg-neutral-700 rounded-lg"
				>
					<span>Экспортировать</span>
					<CiExport className="text-xl" />
				</Button>
				<NextLink
					href={`/admin/${appName}/${modelName}/change`}
					className="bg-green-800 text-white px-4 py-2 rounded-lg flex items-center gap-2  hover:bg-green-700"
				>
					<span>Добавить</span>
					<CiCirclePlus className="text-xl" />
				</NextLink>
			</div>
		</>
	);
};

export function AppTable({ appName, modelName }: { appName: string; modelName: string }) {
	const [tableData, setTableData] = useState({} as any);
	const [loading, setLoading] = useState(true);
	const [appConfig, setAppConfig] = useState<any>(null);

	const config = useAppsConfig();

	useEffect(() => {
		if (config) {
			setAppConfig(config);
		}
	}, [config, setAppConfig]);

	useEffect(() => {
		fetchData(`admin/${appName}/${modelName}/`, "GET")
			.then((data) => {
				setTableData(data);
				setLoading(false);
			})
			.catch((error) => {
				console.error("Error fetching table data:", error);
				setLoading(false);
			});
	}, [appName, setTableData, setLoading]);

	if (loading) {
		return (
			<div className="flex-auto flex justify-center items-center h-screen">
				<Loader />
			</div>
		);
	}

	return (
		<div className="flex flex-col flex-auto h-full overflow-y-auto gap-2">
			<div className="flex justify-between items-center w-full">
				<ActionsHeader appName={appName} modelName={modelName} appConfig={appConfig} />
			</div>

			<div className="w-full overflow-x-auto flex-grow">
				<Table tableData={tableData} />
			</div>
		</div>
	);
}
