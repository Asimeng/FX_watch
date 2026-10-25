library(dplyr)
library(gmailr)
library(stringr)
library(rvest)
library(RSelenium)

# Scrape website ----------------------------------------------------------

# Open Chrome page
rD <- RSelenium::rsDriver(browser =  c("chrome"), port = 7072L, chromever = "latest")

# Assign the client to an object
page <- rD[["client"]]

# Open the FNB forex exchange website
page$navigate("https://www.fnb.co.za/rates/ForeignExchangeRates.html")

# Deal with cookies
accept_cookies <- page$findElement(using = "css selector", value = ".grid--cell")

accept_cookies$highlightElement()

accept_cookies$clickElement()

get_rates <- function(){
  
  # Refresh page for new rates  
  page$refresh()
  
  # Find rates
  show_rates <- page$findElement(using = "css selector",
                                    value = ".iconButtonGroup2 > li:nth-child(1) > a:nth-child(1) > span:nth-child(1)")
  #show_rates$highlightElement()
  show_rates$clickElement()
  
  rates <- page$findElement(using = "css selector",
                               value = "table")
  
  #rates$highlightElement()
  
  # Get the source page to allow rvest functions for further scraping
  rates_page <- page$getPageSource()[[1]]
  
  # Rvest scraping: Extract table to get the euro exchange rate
  forex_rate <- read_html(rates_page) |> 
    html_elements("table") |>
    html_table()
  
  # Clean the table
  euro_rate_tab <- forex_rate[[1]] |> 
    select(!1)
  
  # Replace spaces in column names with an underscore
  new_colnames <- gsub("\\s", "_", colnames(euro_rate_tab))
  colnames(euro_rate_tab) <- new_colnames
  
  # Further cleaning of the table
  tab <- euro_rate_tab |> 
    mutate(Bank_Selling = substr(Bank_Selling, start = 1, stop = 7),
           Bank_Buying = substr(Bank_Buying, start = 1, stop = 7)
           )
  
  rate_of_interest <- tab[[1,4]]
  
  rate_of_interest <- as.numeric(rate_of_interest)
  
  return(rate_of_interest)
}

#rate <- get_rates()

# Send email --------------------------------------------------------------

# Prior to the following steps, configure Google API 
# Refer to https://rpubs.com/bontp/1028597 for tutorials on how to

# Key1.json is the json configuration file you'll get after connecting with Google API
gm_auth_configure(path = "key1.json")

# Authenticate access
gm_auth()

# Send email
send_email <- function(message_body){
  
  new_email <- gm_mime() |> 
    gm_to(c("j.a.asimeng@gmail.com")) |> 
    gm_from("jesseamoakoasimeng@gmail.com") |> 
    gm_subject("Time to exchange your money?") |> 
    gm_text_body(message_body)
  
  gm_send_message(new_email)
  
}

# Putting everything together -------------------------------------------------

rate <- get_rates()

while (TRUE){
  
  if (rate <= 20) {
    
    rate <- get_rates()
    
    #If rate is still less than specified threshold (20), sleep for 15 minutes and repeat
    if (rate <= 20){
      
      Sys.sleep(900)
      
    }
    
  }  else {
    
    message_rate <- paste("\nHi there!\n", 
                          "\nThe Rand to Euro exchange rate is currently\n", rate,
                          "\nYou may want to exchange your money now!\n",
                          "\nKind regards\n",
                          "\nJesse\n")
    
    send_email(message_rate)
    
    break
  }
}
