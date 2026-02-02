(() => {
    const collections = document.querySelectorAll('[data-collection]');
    const landingForm = document.getElementById('landingpageForm');

    const reindexCollection = (section) => {
        const prefix = section.dataset.collection;
        const list = section.querySelector('.collection-list');
        if (!prefix || !list) return;

        Array.from(list.children).forEach((item, index) => {
            item.dataset.index = String(index);
            const fields = item.querySelectorAll('input, select, textarea');
            fields.forEach((field) => {
                const fieldName = field.dataset.field || (() => {
                    const name = field.name || '';
                    const prefixTag = `${prefix}-`;
                    if (!name.startsWith(prefixTag)) return null;
                    const parts = name.slice(prefixTag.length).split('-');
                    return parts.slice(1).join('-') || parts[0];
                })();
                if (!fieldName) return;
                field.name = `${prefix}-${index}-${fieldName}`;
            });
        });
    };

    collections.forEach((section) => {
        const prefix = section.dataset.collection;
        const list = section.querySelector('.collection-list');
        const template = section.querySelector('template');
        const addBtn = section.querySelector('[data-action="add"]');

        if (!list || !template || !addBtn) {
            return;
        }

        let index = list.children.length;

        const applyNames = (item, itemIndex) => {
            const fields = item.querySelectorAll('[data-field]');
            fields.forEach((field) => {
                const fieldName = field.dataset.field;
                if (!fieldName) return;
                field.name = `${prefix}-${itemIndex}-${fieldName}`;
            });
        };

        addBtn.addEventListener('click', () => {
            const clone = template.content.cloneNode(true);
            const item = clone.querySelector('.collection-item');
            if (!item) return;
            item.dataset.index = String(index);
            applyNames(item, index);
            list.appendChild(item);
            index += 1;
        });

        list.addEventListener('click', (event) => {
            const target = event.target;
            if (!(target instanceof HTMLElement)) return;
            const removeBtn = target.closest('[data-action="remove"]');
            if (!removeBtn) return;
            const item = removeBtn.closest('.collection-item');
            if (item) {
                item.remove();
                reindexCollection(section);
            }
        });

        if (window.Sortable) {
            new Sortable(list, {
                animation: 150,
                onEnd: () => reindexCollection(section),
            });
        }
    });

    if (landingForm) {
        landingForm.addEventListener('submit', () => {
            collections.forEach((section) => reindexCollection(section));
        });
    }

    const teacherTable = document.getElementById('teacherTableBody');
    if (teacherTable && window.Sortable) {
        new Sortable(teacherTable, {
            animation: 150,
            handle: '.drag-handle',
            onEnd: () => {
                const ordered = Array.from(teacherTable.querySelectorAll('tr[data-teacher-id]'))
                    .map((row) => row.dataset.teacherId)
                    .filter(Boolean);
                const siteKey = teacherTable.dataset.siteKey || 'default';
                fetch('/settings/landingpage/teachers/reorder', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ site_key: siteKey, order: ordered }),
                }).catch(() => {});
            },
        });
    }

    const cropModalEl = document.getElementById('teacherCropModal');
    const cropImage = document.getElementById('teacherCropImage');
    const cropSaveBtn = document.getElementById('teacherCropSave');
    let cropper = null;
    let currentPhotoTarget = null;
    let currentFileInput = null;

    const resetCropper = () => {
        if (cropper) {
            cropper.destroy();
            cropper = null;
        }
        if (cropImage) {
            cropImage.src = '';
        }
        if (currentFileInput) {
            currentFileInput.value = '';
        }
        currentPhotoTarget = null;
        currentFileInput = null;
    };

    const openCropper = (file, targetInput, fileInput) => {
        if (!cropModalEl || !cropImage || !file || typeof Cropper === 'undefined') return;
        const reader = new FileReader();
        reader.onload = () => {
            cropImage.src = reader.result;
            const modal = window.bootstrap ? new bootstrap.Modal(cropModalEl) : null;
            if (modal) {
                modal.show();
            } else {
                cropModalEl.classList.add('show');
                cropModalEl.style.display = 'block';
            }
            if (cropper) cropper.destroy();
            cropper = new Cropper(cropImage, {
                aspectRatio: 1,
                viewMode: 1,
                autoCropArea: 1,
            });
            currentPhotoTarget = targetInput;
            currentFileInput = fileInput;
        };
        reader.readAsDataURL(file);
    };

    document.querySelectorAll('.teacher-photo-input').forEach((input) => {
        input.addEventListener('change', () => {
            const form = input.closest('[data-photo-form]');
            const targetInput = form ? form.querySelector('input[name=\"photo_data\"]') : null;
            const file = input.files && input.files[0];
            if (file && targetInput) {
                openCropper(file, targetInput, input);
            }
        });
    });

    if (cropSaveBtn && cropModalEl) {
        cropSaveBtn.addEventListener('click', () => {
            if (!cropper || !currentPhotoTarget) return;
            const canvas = cropper.getCroppedCanvas({ width: 512, height: 512 });
            const dataUrl = canvas.toDataURL('image/jpeg', 0.9);
            currentPhotoTarget.value = dataUrl;
            if (currentFileInput) {
                currentFileInput.value = '';
            }
            const modal = window.bootstrap ? bootstrap.Modal.getInstance(cropModalEl) : null;
            if (modal) {
                modal.hide();
            } else {
                cropModalEl.classList.remove('show');
                cropModalEl.style.display = 'none';
            }
            resetCropper();
        });
    }

    if (cropModalEl) {
        cropModalEl.addEventListener('hidden.bs.modal', () => {
            resetCropper();
        });
    }
})();
