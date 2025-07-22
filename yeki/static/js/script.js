$(function(){
  $(window).on('scroll load', function(){
    $('.animate-up').each(function(){
      if($(window).scrollTop()+$(window).height() > $(this).offset().top + 100){
        $(this).addClass('visible');
      }
    });
    $('.animate-fade').each(function(){
      if($(window).scrollTop()+$(window).height() > $(this).offset().top + 100){
        $(this).addClass('visible');
      }
    });
  });
  // Smooth scroll nav
  $('.navbar-nav a').on('click', function(e){
    if(this.hash !== ''){
      e.preventDefault();
      $('html, body').animate({ scrollTop: $(this.hash).offset().top - 70 }, 600);
    }
  });
});
