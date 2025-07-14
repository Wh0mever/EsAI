
import "@/assets/style.scss";
import SectionHero from "@/components/Sections/Hero/Hero";
import SectionFeature from "@/components/Sections/Feature/Feature";
import AiTools from "@/components/Sections/AiTools/AiTools";
import Category from "@/components/Sections/Category/Category";
import Covers from "@/components/Sections/Covers/Covers";
import Pricing from "@/components/Sections/Pricing/Pricing";
import AiApplications from "@/components/Sections/AiApplications/AiApplications";
import FeedBack from "@/components/Sections/Feedback/FeedBack";
import Trial from "@/components/Sections/Trial/Trial";



export default function Home() {
	return (
		<main className="">
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
