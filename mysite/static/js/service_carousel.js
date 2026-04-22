/* Карусель на странице услуги */
const carouselState = {};

function slideCarousel(id, direction) {
    const container = document.getElementById('carousel-' + id);
    if (!container) return;
    const track = container.querySelector('.carousel-track');
    const slides = track.querySelectorAll('.carousel-slide');
    if (!slides.length) return;
    if (!carouselState[id]) carouselState[id] = 0;
    carouselState[id] += direction;
    if (carouselState[id] < 0) carouselState[id] = slides.length - 1;
    if (carouselState[id] >= slides.length) carouselState[id] = 0;
    track.style.transform = 'translateX(-' + (carouselState[id] * 100) + '%)';
    updateDots(id);
}

function goToSlide(id, index) {
    const container = document.getElementById('carousel-' + id);
    if (!container) return;
    const track = container.querySelector('.carousel-track');
    carouselState[id] = index;
    track.style.transform = 'translateX(-' + (index * 100) + '%)';
    updateDots(id);
}

function updateDots(id) {
    const dots = document.querySelectorAll('.carousel-dot[data-carousel="' + id + '"]');
    dots.forEach(function(dot) {
        const idx = parseInt(dot.getAttribute('data-index'));
        dot.style.background = (idx === carouselState[id]) ? '#333' : '#ccc';
    });
}

document.addEventListener('DOMContentLoaded', function() {
    document.querySelectorAll('.service-carousel').forEach(function(carousel) {
        let startX = 0;
        let endX = 0;
        const id = carousel.id.replace('carousel-', '');
        carousel.addEventListener('touchstart', function(e) {
            startX = e.touches[0].clientX;
        }, {passive: true});
        carousel.addEventListener('touchend', function(e) {
            endX = e.changedTouches[0].clientX;
            const diff = startX - endX;
            if (Math.abs(diff) > 50) {
                slideCarousel(id, diff > 0 ? 1 : -1);
            }
        }, {passive: true});
    });
});
