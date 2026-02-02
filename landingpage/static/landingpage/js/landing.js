(() => {
    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const elements = document.querySelectorAll('[data-reveal]');

    if (elements.length) {
        elements.forEach((el) => {
            const variant = (el.getAttribute('data-reveal') || 'up').trim() || 'up';
            const delay = el.getAttribute('data-reveal-delay');
            if (delay) {
                el.style.transitionDelay = `${delay}ms`;
            }
            el.classList.add('reveal', `reveal-${variant}`);
        });

        if (prefersReducedMotion) {
            elements.forEach((el) => el.classList.add('is-visible'));
        } else {
            const observer = new IntersectionObserver(
                (entries) => {
                    entries.forEach((entry) => {
                        const target = entry.target;
                        if (entry.isIntersecting) {
                            target.classList.add('is-visible');
                        } else if (target.dataset.revealOnce !== 'true') {
                            target.classList.remove('is-visible');
                        }
                    });
                },
                { threshold: 0.2, rootMargin: '0px 0px -10% 0px' }
            );

            elements.forEach((el) => observer.observe(el));
        }
    }

    if (prefersReducedMotion) return;

    const hero = document.querySelector('.hero');
    const parallaxItems = Array.from(document.querySelectorAll('[data-parallax]'));
    if (!hero && !parallaxItems.length) return;

    let ticking = false;

    const updateParallax = () => {
        const scrollY = window.scrollY || window.pageYOffset || 0;
        if (hero) {
            const shift = Math.min(scrollY, 600) * 0.18;
            hero.style.setProperty('--hero-shift', `${shift}px`);
        }

        if (parallaxItems.length) {
            const viewHeight = window.innerHeight || 800;
            parallaxItems.forEach((el) => {
                const speed = parseFloat(el.dataset.parallax || '0.12');
                const rect = el.getBoundingClientRect();
                const midpoint = rect.top + rect.height / 2;
                const offset = (viewHeight / 2 - midpoint) * speed;
                el.style.setProperty('--parallax-y', `${offset.toFixed(2)}px`);
            });
        }
        ticking = false;
    };

    const requestTick = () => {
        if (!ticking) {
            window.requestAnimationFrame(updateParallax);
            ticking = true;
        }
    };

    requestTick();
    window.addEventListener('scroll', requestTick, { passive: true });
    window.addEventListener('resize', requestTick);
})();
