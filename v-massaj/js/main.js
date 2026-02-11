(function () {

	"use strict";

	//===== Prealoder

	window.onload = function () {
		window.setTimeout(fadeout, 200);
	}

	function fadeout() {
		document.querySelector('.preloader').style.opacity = '0';
		document.querySelector('.preloader').style.display = 'none';
	}


	/*=====================================
	Sticky
	======================================= */
	window.onscroll = function () {
		var header_navbar = document.querySelector(".navbar-area");
		var sticky = header_navbar.offsetTop;
		
		if (window.pageYOffset > sticky) {
			header_navbar.classList.add("sticky");
			
		} else {
			header_navbar.classList.remove("sticky");
			
		}
	};

if (document.documentElement.clientWidth > 11480) {
	 
	 	  	window.onscroll = function () {
		var header_navbar = document.querySelector(".navbar-area");	
		var left_navbar = document.querySelector(".left-area");
		var sticky = header_navbar.offsetTop;

		if (window.pageYOffset > sticky) {
			left_navbar.classList.add("sticky");
		} else {
			left_navbar.classList.remove("sticky");
		}
	};
  
  }



	
	//===== navbar-toggler
	let navbarToggler = document.querySelector(".navbar-toggler");
	navbarToggler.addEventListener('click', function () {
		navbarToggler.classList.toggle("active");
	})

$(document).on('click', 'section, footer', function () {
         $('.navbar-collapse').collapse('hide');
		 $('.navbar-toggler').removeClass('active');
		  $('.navbar-toggler').addClass('collapsed');
		
    })



	//WOW Scroll Spy
	var wow = new WOW({
		//disabled for mobile
		mobile: false
	});
	wow.init();
	
		

	

if (document.documentElement.clientWidth > 1200) {
$(window).scroll(function(e){
  parallax();
});
function parallax(){
  var scrolled = (($(window).scrollTop() - 600) / 11 - 1);
  $('.home #parallax').css('background-position', '0 '+(-scrolled)+'px');
}
}
/*	
	$('.s-carousel').owlCarousel({
		loop:true,
		margin:30,
		nav:true,
		responsive:{
			0:{
				items:1
			},
			600:{
				items:2
			},
			1000:{
				items:3
			}
		}
	})

*/


})();


// ====== scroll top js
function scrollTo(element, to = 0, duration= 1000) {

	const start = element.scrollTop;
	const change = to - start;
	const increment = 20;
	let currentTime = 0;

	const animateScroll = (() => {

		currentTime += increment;

		// const val = Math.easeInOutQuad(currentTime, start, change, duration);

		// element.scrollTop = val;

		if (currentTime < duration) {
			setTimeout(animateScroll, increment);
		}
	});

	animateScroll();
};

Math.easeInOutQuad = function (t, b, c, d) {

	t /= d/2;
	if (t < 1) return c/2*t*t + b;
	t--;
	return -c/2 * (t*(t-2) - 1) + b;
};

document.querySelector('.scroll-top').onclick = function () {
	scrollTo(document.documentElement); 
}

	
