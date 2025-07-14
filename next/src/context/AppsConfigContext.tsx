// context/AppsConfigContext.tsx
import React, { createContext, useContext, useState, useEffect } from "react";
import { fetchData } from "@/tools/fetchData";

interface AppsConfig {
  [key: string]: any;
}

const AppsConfigContext = createContext<AppsConfig | undefined>(undefined);

export const useAppsConfig = () => {
  const context = useContext(AppsConfigContext);
  if (!context) {
    return undefined; 
  }
  return context;
};

export const AppsConfigProvider = ({ children }: { children: React.ReactNode }) => {
  const [appsConfig, setAppsConfig] = useState<AppsConfig | undefined>(undefined);

  useEffect(() => {
    fetchData("admin/apps/")
      .then((data) => {
        setAppsConfig(data);
      })
      .catch((error) => {
        console.error("Error fetching apps config:", error);
      });
  }, []);

  return (
    <AppsConfigContext.Provider value={appsConfig}>
      {children}
    </AppsConfigContext.Provider>
  );
};
