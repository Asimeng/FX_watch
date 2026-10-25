library(dplyr)
library(stringr)
library(purrr)
library(rvest)
library(RSelenium)


wdman::selenium(retcommand = T)

rD <- RSelenium::rsDriver(browser = c("chrome"), port = 7072L, chromever = "latest") # This might throw an error

binman::list_versions(appname = "chromedriver")


# Assign the client to an object
remDr <- rD[["client"]]

remDr$navigate("https://www.fnb.co.za/rates/ForeignExchangeRates.html")

remDr$getPageSource()[[1]]

accept_cookies <- remDr$findElement(using = "css selector", value = ".grid--cell")

accept_cookies$highlightElement()

accept_cookies$clickElement()

show_rates <- remDr$findElement(using = "css selector",
                                value = ".iconButtonGroup2 > li:nth-child(1) > a:nth-child(1) > span:nth-child(1)")
show_rates$highlightElement()
show_rates$clickElement()

rates <- remDr$findElement(using = "css selector",
                           value = "table")

rates$highlightElement()

# Get the source page to allow rvest functions for further scraping
rates_page <- remDr$getPageSource()[[1]]

# Rvest scraping: Get table for euro exchange
forex_rate <- read_html(rates_page) |> 
  html_elements("table") |> 
  html_table()

# Clean the table
euro_rate_tab <- forex_rate[[1]] |> 
  select(!1)


tab <- euro_rate_tab |> 
  mutate(`Bank Selling` = str_split(`Bank Selling`, "\n")[[1]][1],
         `Bank Buying` = str_split(`Bank Buying`, "\n")[[1]][1])
  



##### R4DS #######

# Pivoting

billboard_longer <- billboard |> 

pivot_longer(
  cols = starts_with("wk"),
  names_to = "week",
  values_to = "rank",
  values_drop_na = TRUE
) |>
mutate(
  week = parse_number(week)
)


billboard_longer |> 
  ggplot(aes(x = week, y = rank, group = track))+
  geom_line(alpha = 0.25) +
  scale_y_reverse()


who2 |> 
  pivot_longer(
    cols = !c(country, year),
    names_to = c("diagnosis", "gender", "age"),
    names_sep = "_",
    values_to = "count"
  )

# .value is a special sentinel
household |> 
  pivot_longer(
    cols = !family,
    names_to = c(".value", "child"),
    names_sep = "_",
    values_drop_na = TRUE
  )



### Pivot wider use

cms_patient_experience |> 
  pivot_wider(
    id_cols = starts_with("org"),
    names_from = measure_cd,
    values_from = prf_rate
  )
 