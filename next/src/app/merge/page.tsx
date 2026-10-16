import MergeStudio from "@/components/merge/MergeStudio";

// Склейка видео: свои готовые ролики из видеостудии, мультстудии и чата — в
// один. Открытая склейка — в адресе (?id=<uid>); «Открыть в склейке» из
// мультстудии приходит с ?add=cartoon_movie:<id> и заводит склейку с ним.
export default function MergePage() {
	return <MergeStudio />;
}
