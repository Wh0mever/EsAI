
import "@/assets/style.scss";
import SectionHero from "@/components/sections/Hero/Hero";
import SectionFeature from "@/components/sections/Feature/Feature";
import AiTools from "@/components/sections/AiTools/AiTools";
import Category from "@/components/sections/Category/Category";
import Covers from "@/components/sections/Covers/Covers";
import Pricing from "@/components/sections/Pricing/Pricing";
import AiApplications from "@/components/sections/AiApplications/AiApplications";
import FeedBack from "@/components/sections/Feedback/FeedBack";
import Trial from "@/components/sections/Trial/Trial";



export default function Home() {
	return (
		<main  className="pb-10">
			<SectionHero />
			<SectionFeature />
			<AiTools />
			<Category />
			<Covers />
			<Pricing />
			<AiApplications />
			<FeedBack />
			<Trial />
		</main>
	);
}
