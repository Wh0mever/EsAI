export default function formEntries(form: HTMLFormElement) {
	const formData = new FormData(form);
    const entries: any = {}
	for (let [key, value] of formData.entries()) {
        entries[key] = value;
	}
    return entries;
}
