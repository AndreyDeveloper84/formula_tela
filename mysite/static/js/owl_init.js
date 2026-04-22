/* Инициализация Owl Carousel для .o-carousel */
$(document).ready(function() {
    if ($('.o-carousel').length) {
        $('.o-carousel').owlCarousel({
            loop: true,
            margin: 16,
            nav: false,
            responsive: {
                0:    { items: 1 },
                600:  { items: 2 },
                1000: { items: 3 }
            }
        });
    }
});
