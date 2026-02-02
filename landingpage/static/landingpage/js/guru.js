(() => {
    const filterEl = document.getElementById('guruFilter');
    const searchEl = document.getElementById('guruSearch');
    const emptyEl = document.getElementById('guruEmpty');
    const cards = Array.from(document.querySelectorAll('.guru-card'));

    if (!filterEl || !searchEl || !cards.length) {
        return;
    }

    const applyFilter = () => {
        const filterValue = (filterEl.value || '').toLowerCase();
        const query = (searchEl.value || '').trim().toLowerCase();
        let visibleCount = 0;

        cards.forEach((card) => {
            const jabatan = card.dataset.jabatan || '';
            const nama = card.dataset.nama || '';
            const email = card.dataset.email || '';
            const matchFilter = filterValue === 'semua' || jabatan.includes(filterValue);
            const matchQuery = !query || nama.includes(query) || email.includes(query);
            const visible = matchFilter && matchQuery;
            card.style.display = visible ? '' : 'none';
            if (visible) {
                visibleCount += 1;
            }
        });

        if (emptyEl) {
            emptyEl.style.display = visibleCount ? 'none' : 'block';
        }
    };

    filterEl.addEventListener('change', applyFilter);
    searchEl.addEventListener('input', applyFilter);

    applyFilter();
})();
